"""Splitting a trip's costs evenly, what other travellers paid, settling up, and what
a share link shows. Every name and figure here is made up."""

import asyncio
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.service import AgentService, Reply
from nexus.application import bookings as booking_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application import trip_split as split_trip
from nexus.application import trips as trip_cases
from nexus.application.ports import LedgerQuery
from nexus.application.splits import split_bill
from nexus.domain.errors import Conflict, InvalidInput, NotFound
from nexus.domain.ledger import Direction, ShareRequest, User
from nexus.domain.money import Money
from nexus.domain.settle import Direction as Owing
from nexus.domain.trips import Trip
from nexus.infra.db.migrations import alembic_config
from tests.fakes import FakeRates, ScriptedModel, call, say, scripted
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_agent import build, tool_results
from tests.integration.test_email import person
from tests.integration.test_trips import draft, sgd, spend

pytestmark = pytest.mark.integration

SG = ZoneInfo("Asia/Singapore")
MADE = datetime(2026, 11, 2, 9, tzinfo=SG)
AFTER = datetime(2027, 1, 25, 12, tzinfo=SG)
RATES = FakeRates({("JPY", "SGD"): {date(2026, 11, 1): "0.0090"}})


def jpy(amount: str) -> Money:
    return Money.of(amount, "JPY")


def on_day(day: int) -> datetime:
    return datetime(2027, 1, day, 13, tzinfo=SG)


async def going(
    uow: UowFactory, *, companions: list[str] | None = None, currency: str = "JPY"
) -> tuple[User, Trip]:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(), user,
        draft(companions=["Alex", "Sam"] if companions is None else companions, currency=currency),
        now=MADE,
    )  # fmt: skip
    return user, trip


async def view(uow: UowFactory, user: User, trip: Trip) -> trip_cases.TripView:
    return await trip_cases.trip_view(uow, RATES, user, trip.id, now=AFTER)


async def ledger(uow: UowFactory, user: User) -> list[tuple[Direction, Money, str | None]]:
    page = await tx_cases.list_ledger(uow(), user.id, LedgerQuery(limit=100))
    return sorted(
        ((t.direction, t.amount, t.counterparty) for t in page.items), key=lambda r: str(r)
    )


# --- what's offered, and splitting it ---------------------------------------------------


async def test_costs_not_split_are_offered_and_split_evenly_with_everyone(
    uow: UowFactory,
) -> None:
    user, trip = await going(uow)
    hotel = await spend(uow, user, "12000", on_day(10))
    ramen = await spend(uow, user, "6000", on_day(11))
    taxi = await spend(uow, user, "3000", on_day(12))
    # Not the trip's: another currency, off the dates, and money in.
    await spend(uow, user, "15", on_day(11), currency="SGD")
    await spend(uow, user, "500", datetime(2027, 1, 9, 23, tzinfo=SG))
    await spend(uow, user, "900", on_day(11), direction=Direction.IN)

    before = await view(uow, user, trip)
    assert [i.transaction_id for i in before.to_split] == [taxi, ramen, hotel]  # newest first
    assert before.spending.spent == sgd("189")  # 21,000 yen at 0.009

    await split_trip.keep_mine(uow(), user, trip.id, [taxi])
    assert [i.transaction_id for i in (await view(uow, user, trip)).to_split] == [ramen, hotel]
    assert (await view(uow, user, trip)).just_mine == [taxi]

    out = await split_trip.split_trip_costs(uow, RATES, user, trip.id, now=AFTER)
    assert out.with_people == ["Alex", "Sam"] and out.skipped == []
    assert {d.transaction_id: (d.amount, d.own_share) for d in out.done} == {
        hotel: (jpy("12000"), jpy("4000")),
        ramen: (jpy("6000"), jpy("2000")),
    }

    after = await view(uow, user, trip)
    assert after.to_split == [] and after.just_mine == [taxi]
    # Only the user's third of the two bills counts now, plus the taxi in full.
    assert after.spending.spent == sgd("81")  # 4,000 + 2,000 + 3,000 yen
    assert [(o.name, o.amounts, o.home) for o in after.owed] == [
        ("Alex", [jpy("6000")], sgd("54")),
        ("Sam", [jpy("6000")], sgd("54")),
    ]
    assert [(b.name, b.net_home) for b in after.balances] == [
        ("Alex", sgd("54")),
        ("Sam", sgd("54")),
    ]

    # Splitting again finds nothing, and asking for a split bill by id leaves it alone.
    again = await split_trip.split_trip_costs(uow, RATES, user, trip.id, now=AFTER)
    assert again.done == [] and again.skipped == []
    named = await split_trip.split_trip_costs(uow, RATES, user, trip.id, [hotel], now=AFTER)
    assert named.done == [] and [(s.transaction_id, s.reason) for s in named.skipped] == [
        (hotel, "this bill is already split")
    ]
    assert (await view(uow, user, trip)).spending.spent == sgd("81")


async def test_a_cost_marked_just_mine_can_still_be_split_by_asking_and_offered_again(
    uow: UowFactory,
) -> None:
    user, trip = await going(uow, companions=["Alex"])
    lunch = await spend(uow, user, "4000", on_day(10))
    dinner = await spend(uow, user, "8000", on_day(10))
    await split_trip.keep_mine(uow(), user, trip.id, [lunch, dinner])
    assert (await view(uow, user, trip)).to_split == []
    assert await split_trip.unsplit_expenses(uow, RATES, user, trip) == []
    # Marking the same one twice keeps it once.
    await split_trip.keep_mine(uow(), user, trip.id, [lunch])
    assert (await view(uow, user, trip)).just_mine == [lunch, dinner]

    # Offered again.
    await split_trip.keep_mine(uow(), user, trip.id, [lunch], keep=False)
    assert [i.transaction_id for i in (await view(uow, user, trip)).to_split] == [lunch]

    # "Split all" leaves the one still marked alone; naming it splits it and lets it go.
    out = await split_trip.split_trip_costs(uow, RATES, user, trip.id, now=AFTER)
    assert [d.transaction_id for d in out.done] == [lunch]
    named = await split_trip.split_trip_costs(uow, RATES, user, trip.id, [dinner], now=AFTER)
    assert [d.transaction_id for d in named.done] == [dinner]
    assert (await view(uow, user, trip)).just_mine == []


async def test_nothing_is_offered_or_split_without_other_travellers_or_when_switched_off(
    uow: UowFactory,
) -> None:
    alone_user, alone = await going(uow, companions=[])
    await spend(uow, alone_user, "4000", on_day(10))
    assert (await view(uow, alone_user, alone)).to_split == []
    with pytest.raises(InvalidInput, match="people you're travelling with"):
        await split_trip.split_trip_costs(uow, RATES, alone_user, alone.id, now=AFTER)

    user = await person(uow, 5151)
    trip = await trip_cases.create_trip(
        uow(), user, draft(companions=["Alex"]), now=MADE
    )  # fmt: skip
    cost = await spend(uow, user, "4000", on_day(10))
    assert trip.split_evenly and (await view(uow, user, trip)).trip.split_evenly
    assert len((await view(uow, user, trip)).to_split) == 1

    off = await split_trip.set_split_evenly(uow(), user, trip.id, False)
    assert off.split_evenly is False
    shown = await view(uow, user, trip)
    assert shown.to_split == [] and shown.trip.split_evenly is False
    # Nothing in the ledger changed, and the user can still split on purpose.
    assert shown.owed == []
    done = await split_trip.split_trip_costs(uow, RATES, user, trip.id, [cost], now=AFTER)
    assert [d.transaction_id for d in done.done] == [cost]

    # Editing the trip keeps both settings.
    await split_trip.keep_mine(uow(), user, trip.id, [cost])
    edited = await trip_cases.update_trip(
        uow(), user, trip.id, trip_cases.draft_of(trip), now=AFTER
    )  # fmt: skip
    assert edited.split_evenly is False and edited.not_split == (cost,)
    assert (await trip_cases.get_trip(uow(), user.id, trip.id)).not_split == (cost,)
    on = await split_trip.set_split_evenly(uow(), user, trip.id, True)
    assert on.split_evenly is True


async def test_an_expense_split_meanwhile_or_not_on_the_trip_is_skipped_not_changed(
    uow: UowFactory,
) -> None:
    user, trip = await going(uow)
    mine = await spend(uow, user, "9000", on_day(10))
    shared = await spend(uow, user, "6000", on_day(11))
    # Split another way, by hand, after it was listed.
    await split_bill(uow(), user.id, shared, [ShareRequest("Alex")], include_self=False)
    elsewhere = await spend(uow, user, "700", on_day(12), currency="SGD")
    stranger = await person(uow, 9191)
    theirs = await spend(uow, stranger, "5000", on_day(12))

    out = await split_trip.split_trip_costs(
        uow, RATES, user, trip.id, [mine, shared, elsewhere, theirs, uuid4()], now=AFTER
    )
    assert [d.transaction_id for d in out.done] == [mine]
    reasons = {s.transaction_id: s.reason for s in out.skipped}
    assert reasons[shared] == "this bill is already split"
    assert reasons[elsewhere] == reasons[theirs] == "not an expense on this trip"
    assert len(out.skipped) == 5 - 1
    # Their split by hand is as it was: Alex owes the whole of it.
    ious = await split_cases.list_open_ious(uow(), user.id, participant_name="Alex")
    assert sorted(i.outstanding.amount for i in ious) == [3000, 6000]  # 3,000 and 6,000 yen
    assert await split_cases.list_open_ious(uow(), stranger.id) == []


async def test_keeping_a_cost_mine_needs_it_to_be_on_the_trip_and_theirs(uow: UowFactory) -> None:
    user, trip = await going(uow)
    stranger = await person(uow, 9191)
    theirs = await spend(uow, stranger, "5000", on_day(12))
    other_currency = await spend(uow, user, "9", on_day(12), currency="SGD")
    for bad in (theirs, other_currency, uuid4()):
        with pytest.raises(NotFound):
            await split_trip.keep_mine(uow(), user, trip.id, [bad])
    assert (await trip_cases.get_trip(uow(), user.id, trip.id)).not_split == ()


# --- what other people paid -------------------------------------------------------------


async def test_what_alex_paid_is_owed_back_in_equal_parts_and_nets_against_their_shares(
    uow: UowFactory,
) -> None:
    user, trip = await going(uow)
    hotel = await spend(uow, user, "12000", on_day(10))
    await split_trip.split_trip_costs(uow, RATES, user, trip.id, [hotel], now=AFTER)
    # Alex owes 4,000 yen (36 SGD); Alex paid 460 SGD, split three ways: 153.34 for the user.
    paid = await split_trip.add_paid_by_other(
        uow(), user, trip.id, person="alex", amount=sgd("460"), note="  the ryokan ",
        paid_on=date(2027, 1, 11), split_with=None, now=AFTER,
    )  # fmt: skip
    assert (paid.person, paid.note, paid.split_with) == ("Alex", "the ryokan", ("Sam",))
    assert (paid.sharers, paid.my_share, paid.settled) == (3, sgd("153.34"), False)

    shown = await view(uow, user, trip)
    assert shown.paid_by_others == [paid]
    by_name = {b.name: b for b in shown.balances}
    alex = by_name["Alex"]
    assert alex.net_home == sgd("-117.34") and alex.direction is Owing.YOU_OWE  # 36 - 153.34
    assert [(d.kind.value, d.amount, d.label) for d in alex.you_owe] == [
        ("payment", sgd("153.34"), "the ryokan")
    ]
    assert [(d.kind.value, d.amount) for d in alex.owes_you] == [("iou", jpy("4000"))]
    assert by_name["Sam"].net_home == sgd("36")
    # It is a note, not spending: the ledger and the trip's spending are untouched.
    assert shown.spending.spent == sgd("36")  # the user's third of the hotel
    assert len(await ledger(uow, user)) == 1

    lines = "\n".join(trip_cases.describe_view(shown))
    assert "Alex paid 460.00 SGD for the ryokan (the user's share 153.34 SGD)" in lines
    assert "You owe Alex 117.34 SGD" in lines and "Sam owes you 36.00 SGD" in lines


async def test_a_payment_can_be_shared_by_some_changed_and_removed(uow: UowFactory) -> None:
    user, trip = await going(uow, companions=["Alex", "Sam", "Wei Ming"])
    paid = await split_trip.add_paid_by_other(
        uow(), user, trip.id, person="Sam", amount=jpy("9000"), note=None,
        paid_on=date(2027, 1, 12), split_with=["wei ming"], now=AFTER,
    )  # fmt: skip
    assert (paid.split_with, paid.my_share) == (("Wei Ming",), jpy("3000"))
    changed = await split_trip.edit_paid_by_other(
        uow(), user, trip.id, paid.id, person="Alex", amount=jpy("10000"), note="Tickets",
        paid_on=date(2027, 1, 13), split_with=["Sam"],
    )  # fmt: skip
    assert (changed.id, changed.person, changed.split_with) == (paid.id, "Alex", ("Sam",))
    assert changed.my_share == jpy("3334")  # three ways, the user's share first
    [stored] = (await view(uow, user, trip)).paid_by_others
    assert stored == changed

    await split_trip.delete_paid_by_other(uow(), user, trip.id, paid.id)
    assert (await view(uow, user, trip)).paid_by_others == []
    assert (await view(uow, user, trip)).balances == []
    with pytest.raises(NotFound):
        await split_trip.delete_paid_by_other(uow(), user, trip.id, paid.id)


async def test_a_payment_needs_a_traveller_a_sensible_amount_and_sharers_on_the_trip(
    uow: UowFactory,
) -> None:
    user, trip = await going(uow)

    async def add(**changes: object) -> None:
        args: dict[str, object] = {
            "person": "Alex", "amount": sgd("10"), "note": None, "paid_on": date(2027, 1, 12),
            "split_with": None, "now": AFTER,
        }  # fmt: skip
        await split_trip.add_paid_by_other(uow(), user, trip.id, **{**args, **changes})  # type: ignore[arg-type]

    with pytest.raises(InvalidInput, match="Zoe isn't on this trip"):
        await add(person="Zoe")
    with pytest.raises(InvalidInput, match="Zoe isn't on this trip"):
        await add(split_with=["Zoe"])
    with pytest.raises(InvalidInput):
        await add(amount=sgd("0"))
    with pytest.raises(InvalidInput):
        await add(amount=sgd("-3"))
    with pytest.raises(InvalidInput):
        await add(amount=jpy("10.5"))
    with pytest.raises(InvalidInput, match=r"longer than 100"):
        await add(note="x" * 101)
    assert (await view(uow, user, trip)).paid_by_others == []


async def test_a_payment_can_only_be_changed_until_it_is_settled(uow: UowFactory) -> None:
    user, trip = await going(uow, companions=["Alex"])
    paid = await split_trip.add_paid_by_other(
        uow(), user, trip.id, person="Alex", amount=sgd("100"), note="Dinner",
        paid_on=date(2027, 1, 12), split_with=None, now=AFTER,
    )  # fmt: skip
    await split_trip.settle_person(uow, RATES, user, trip.id, "Alex", log=True, now=AFTER)
    with pytest.raises(Conflict):
        await split_trip.edit_paid_by_other(
            uow(), user, trip.id, paid.id, person="Alex", amount=sgd("90"), note=None,
            paid_on=date(2027, 1, 12), split_with=None,
        )  # fmt: skip


# --- settling up -------------------------------------------------------------------------


async def alex_and_sam_owe_and_alex_paid(
    uow: UowFactory,
) -> tuple[User, Trip, UUID]:
    user, trip = await going(uow)
    hotel = await spend(uow, user, "12000", on_day(10))
    await split_trip.split_trip_costs(uow, RATES, user, trip.id, [hotel], now=AFTER)
    await split_trip.add_paid_by_other(
        uow(), user, trip.id, person="Alex", amount=sgd("460"), note="the ryokan",
        paid_on=date(2027, 1, 11), split_with=["Sam"], now=AFTER,
    )  # fmt: skip
    return user, trip, hotel


async def test_settling_up_records_what_alex_paid_and_what_alex_owed_and_nothing_twice(
    uow: UowFactory,
) -> None:
    user, trip, _ = await alex_and_sam_owe_and_alex_paid(uow)
    assert len(await ledger(uow, user)) == 1  # the hotel

    done = await split_trip.settle_person(uow, RATES, user, trip.id, "ALEX", log=True, now=AFTER)
    assert (done.person, done.ious_repaid, done.payments_settled) == ("Alex", 1, 1)
    # Money in for the share Alex paid back, money out for the user's share of the ryokan.
    assert [(t.direction, t.amount, t.counterparty) for t in done.income] == [
        (Direction.IN, jpy("4000"), "Alex")
    ]
    [spent] = done.expenses
    assert (spent.direction, spent.amount, spent.counterparty) == (
        Direction.OUT,
        sgd("153.34"),
        "Alex",
    )
    assert spent.occurred_at.astimezone(SG).date() == date(2027, 1, 11)  # the day it was paid
    assert spent.notes == "Your share of the ryokan (Tokyo)"
    assert len(await ledger(uow, user)) == 3

    after = await view(uow, user, trip)
    assert [b.name for b in after.balances] == ["Sam"]  # Alex is square, Sam still owes
    [paid] = after.paid_by_others
    assert paid.settled and paid.settled_at == AFTER
    assert await split_cases.list_open_ious(uow(), user.id, participant_name="Sam") != []
    # The user's share now counts towards the trip, and isn't offered for splitting.
    assert [i.transaction_id for i in after.items if i.transaction_id == spent.id] == [spent.id]
    assert after.spending.spent == sgd("189.34")  # a third of the hotel, and the ryokan share
    assert after.to_split == [] and spent.id in after.trip.not_split

    with pytest.raises(InvalidInput, match="nothing to settle with Alex"):
        await split_trip.settle_person(uow, RATES, user, trip.id, "Alex", log=True, now=AFTER)
    assert len(await ledger(uow, user)) == 3


async def test_settling_up_without_logging_keeps_the_users_share_out_of_the_ledger(
    uow: UowFactory,
) -> None:
    user, trip, _ = await alex_and_sam_owe_and_alex_paid(uow)
    done = await split_trip.settle_person(uow, RATES, user, trip.id, "Alex", log=False, now=AFTER)
    assert (done.ious_repaid, done.payments_settled, done.expenses) == (1, 1, [])
    # Marking a share paid back always records the money in, as it does everywhere.
    assert len(done.income) == 1 and len(await ledger(uow, user)) == 2
    assert [b.name for b in (await view(uow, user, trip)).balances] == ["Sam"]


async def test_settling_up_with_someone_the_user_only_owes_or_is_only_owed(
    uow: UowFactory,
) -> None:
    user, trip, _ = await alex_and_sam_owe_and_alex_paid(uow)
    sam = await split_trip.settle_person(uow, RATES, user, trip.id, "sam", log=True, now=AFTER)
    assert (sam.ious_repaid, sam.payments_settled, sam.expenses) == (1, 0, [])

    alex = await split_trip.settle_person(uow, RATES, user, trip.id, "Alex", log=True, now=AFTER)
    assert (alex.ious_repaid, alex.payments_settled) == (1, 1)
    assert (await view(uow, user, trip)).balances == []

    # Only a payment: the user paid Alex their share, and nothing came in.
    user2 = await person(uow, 5252)
    trip2 = await trip_cases.create_trip(uow(), user2, draft(companions=["Alex"]), now=MADE)
    await split_trip.add_paid_by_other(
        uow(), user2, trip2.id, person="Alex", amount=sgd("50"), note=None,
        paid_on=date(2027, 1, 11), split_with=None, now=AFTER,
    )  # fmt: skip
    paid_back = await split_trip.settle_person(
        uow, RATES, user2, trip2.id, "Alex", log=True, now=AFTER
    )
    assert (paid_back.ious_repaid, paid_back.income) == (0, [])
    assert [(t.direction, t.amount, t.notes) for t in paid_back.expenses] == [
        (Direction.OUT, sgd("25"), "Your share of a trip cost (Tokyo)")
    ]


async def test_someone_with_nothing_open_cannot_be_settled(uow: UowFactory) -> None:
    user, trip = await going(uow)
    with pytest.raises(InvalidInput, match="nothing to settle with Alex"):
        await split_trip.settle_person(uow, RATES, user, trip.id, "Alex", log=True, now=AFTER)
    with pytest.raises(InvalidInput, match="nothing to settle with Zoe"):
        await split_trip.settle_person(uow, RATES, user, trip.id, "Zoe", log=True, now=AFTER)


async def test_balances_with_a_missing_rate_keep_the_parts(uow: UowFactory) -> None:
    user, trip = await going(uow, companions=["Alex"])
    cost = await spend(uow, user, "6000", on_day(10))
    await split_trip.split_trip_costs(uow, RATES, user, trip.id, [cost], now=AFTER)
    await split_trip.add_paid_by_other(
        uow(), user, trip.id, person="Alex", amount=Money.of("40", "USD"), note=None,
        paid_on=date(2027, 1, 11), split_with=None, now=AFTER,
    )  # fmt: skip
    [alex] = (await view(uow, user, trip)).balances  # no USD rate: no single total
    assert alex.net_home is None and alex.direction is None
    assert alex.net_by_currency == [jpy("3000"), Money.of("-20", "USD")]
    # It can still be settled: each thing is recorded in its own currency.
    done = await split_trip.settle_person(uow, RATES, user, trip.id, "Alex", log=True, now=AFTER)
    assert [t.amount for t in done.expenses] == [Money.of("20", "USD")]
    assert [t.amount for t in done.income] == [jpy("3000")]


# --- other people's trips ----------------------------------------------------------------


async def test_another_user_can_neither_see_nor_change_a_trips_split_or_payments(
    uow: UowFactory,
) -> None:
    user, trip, hotel = await alex_and_sam_owe_and_alex_paid(uow)
    [paid] = (await view(uow, user, trip)).paid_by_others
    stranger = await person(uow, 9191)
    other = await trip_cases.create_trip(
        uow(), stranger, draft(companions=["Alex"]), now=MADE
    )  # fmt: skip

    with pytest.raises(NotFound):
        await split_trip.set_split_evenly(uow(), stranger, trip.id, False)
    with pytest.raises(NotFound):
        await split_trip.keep_mine(uow(), stranger, trip.id, [hotel])
    with pytest.raises(NotFound):
        await split_trip.split_trip_costs(uow, RATES, stranger, trip.id, now=AFTER)
    with pytest.raises(NotFound):
        await split_trip.add_paid_by_other(
            uow(), stranger, trip.id, person="Alex", amount=sgd("5"), note=None,
            paid_on=date(2027, 1, 11), split_with=None, now=AFTER,
        )  # fmt: skip
    with pytest.raises(NotFound):
        await split_trip.settle_person(uow, RATES, stranger, trip.id, "Alex", log=True, now=AFTER)
    with pytest.raises(NotFound):
        await trip_cases.trip_view(uow, RATES, stranger, trip.id, now=AFTER)
    # Not through their own trip either, nor with the payment's id.
    with pytest.raises(NotFound):
        await split_trip.delete_paid_by_other(uow(), stranger, other.id, paid.id)
    with pytest.raises(NotFound):
        await split_trip.edit_paid_by_other(
            uow(), stranger, other.id, paid.id, person="Alex", amount=sgd("1"), note=None,
            paid_on=date(2027, 1, 11), split_with=None,
        )  # fmt: skip
    with pytest.raises(NotFound):
        await split_trip.delete_paid_by_other(uow(), stranger, trip.id, paid.id)
    # Nothing changed for the owner.
    after = await view(uow, user, trip)
    assert (
        after.paid_by_others == [paid]
        and after.trip.split_evenly
        and not after.paid_by_others[0].settled
    )
    assert len(await ledger(uow, user)) == 1
    assert (await view(uow, stranger, other)).paid_by_others == []


# --- the link ----------------------------------------------------------------------------


async def test_a_link_hides_flights_stays_and_tickets_but_keeps_the_users_own_plans(
    uow: UowFactory,
) -> None:
    user, trip = await going(uow)
    entries: list[dict[str, object]] = [
        {"kind": "hotel", "hotel": "Hotel Kumo", "check_in": "2027-01-10",
         "check_out": "2027-01-14", "reference": "HK55821"},
        {"kind": "flight", "segments": [{"number": "ZZ12", "origin": "SIN", "destination": "NRT",
         "departs": "2027-01-10T08:25", "arrives": "2027-01-10T16:10"}]},
        {"kind": "activity", "name": "Dinner at Sushi Ten", "day": "2027-01-11", "at": "19:00"},
        {"kind": "activity", "name": "Museum entry", "day": "2027-01-12", "booked_via": "Klook"},
    ]  # fmt: skip
    for entry in entries:
        await booking_cases.add_manual(uow(), user.id, trip.id, entry, None, now=MADE)

    on = await trip_cases.share_trip(uow(), user.id, trip.id, renew=False, now=MADE)
    assert on.show_bookings is True
    shown = await trip_cases.open_shared(uow(), on.token)
    assert shown.show_bookings and shown.hidden_days == []
    assert len(shown.bookings) == 4

    off = await trip_cases.share_trip(
        uow(), user.id, trip.id, renew=False, show_bookings=False, now=MADE
    )
    assert off.token == on.token and off.show_bookings is False  # the same link
    hidden = await trip_cases.open_shared(uow(), on.token)
    assert not hidden.show_bookings
    assert [b.draft.name for b in hidden.bookings] == ["Dinner at Sushi Ten"]
    # Days the hidden ones start or end on, with nothing else about them.
    assert hidden.hidden_days == [date(2027, 1, 10), date(2027, 1, 12), date(2027, 1, 14)]

    # Asking again without saying keeps the setting; a new link keeps it too.
    assert (await trip_cases.share_trip(uow(), user.id, trip.id, renew=False, now=MADE)) == off
    renewed = await trip_cases.share_trip(uow(), user.id, trip.id, renew=True, now=MADE)
    assert renewed.token != on.token and renewed.show_bookings is False
    with pytest.raises(NotFound):
        await trip_cases.open_shared(uow(), on.token)
    again = await trip_cases.share_trip(
        uow(), user.id, trip.id, renew=True, show_bookings=True, now=MADE
    )
    assert again.show_bookings is True
    assert (await trip_cases.share_link(uow(), user.id, trip.id)) == again

    # Stopping and sharing again starts over: on.
    await trip_cases.stop_sharing(uow(), user.id, trip.id)
    assert await trip_cases.share_link(uow(), user.id, trip.id) is None
    fresh = await trip_cases.share_trip(uow(), user.id, trip.id, renew=False, now=MADE)
    assert fresh.show_bookings is True

    stranger = await person(uow, 9191)
    with pytest.raises(NotFound):
        await trip_cases.share_trip(
            uow(), stranger.id, trip.id, renew=False, show_bookings=False, now=MADE
        )
    assert (await trip_cases.share_link(uow(), user.id, trip.id)) == fresh


# --- the migration -----------------------------------------------------------------------


async def test_the_migration_adds_the_columns_with_defaults_and_keeps_trips_and_links(
    engine: AsyncEngine, uow: UowFactory, empty_database_url: str
) -> None:
    user, trip = await going(uow)
    await trip_cases.share_trip(uow(), user.id, trip.id, renew=False, show_bookings=False, now=MADE)
    await split_trip.add_paid_by_other(
        uow(), user, trip.id, person="Alex", amount=sgd("10"), note=None,
        paid_on=date(2027, 1, 11), split_with=None, now=AFTER,
    )  # fmt: skip
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0044")
    async with engine.connect() as db:
        columns: set[str] = set(
            (
                await db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name IN ('trips', 'trip_shares')"
                    )
                )
            ).scalars()
        )
        tables: set[str] = set(
            (await db.execute(text("SELECT table_name FROM information_schema.tables"))).scalars()
        )
    assert not {"split_evenly", "not_split", "show_bookings"} & columns
    assert "trip_paid_by_others" not in tables

    await upgrade(empty_database_url)
    async with engine.connect() as db:
        trips = (
            await db.execute(text("SELECT destination, split_evenly, not_split FROM trips"))
        ).all()
        shares = (await db.execute(text("SELECT show_bookings FROM trip_shares"))).all()
    # Existing trips split evenly (once anyone else is going) and existing links show
    # bookings, as they always did.
    assert [(r.destination, r.split_evenly, r.not_split) for r in trips] == [("Tokyo", True, [])]
    assert [r.show_bookings for r in shares] == [True]


# --- in chat -----------------------------------------------------------------------------


def chat(uow: UowFactory, model: ScriptedModel) -> AgentService:
    return build(uow, model)


async def asked(agent: AgentService, user: User, text: str, key: str) -> Reply:
    [reply] = await agent.handle_text(user.id, text, key)
    return reply


async def test_chat_splits_the_trips_costs_after_asking(uow: UowFactory) -> None:
    user, _ = await going(uow, companions=["Ann", "Ben"], currency="SGD")
    hotel = await spend(uow, user, "120", on_day(10), currency="SGD")
    ramen = await spend(uow, user, "30", on_day(11), currency="SGD")
    model = scripted(call("split_trip_costs", trip="tokyo"), say("Done."))
    agent = chat(uow, model)
    reply = await asked(agent, user, "split the tokyo costs with ann and ben", "tg:1:1")
    assert reply.text == (
        "Split 2 costs on the Tokyo trip (150.00 SGD) evenly with Ann and Ben, you taking "
        "an equal share?"
    )
    assert await split_cases.list_open_ious(uow(), user.id) == []  # nothing until they say yes
    await agent.resolve(user.id, reply.buttons[0][0].data.split(":")[1], True)
    [result] = tool_results(model)
    assert result == (
        "Split 2 costs on the Tokyo trip evenly with Ann and Ben; your share is 50.00 SGD "
        "and the rest is owed to you."
    )
    ious = await split_cases.list_open_ious(uow(), user.id)
    assert sorted((i.split.participant_name, i.outstanding.amount) for i in ious) == [
        ("Ann", Decimal("10")),
        ("Ann", Decimal("40")),
        ("Ben", Decimal("10")),
        ("Ben", Decimal("40")),
    ]
    assert {i.split.transaction_id for i in ious} == {hotel, ramen}


async def test_chat_says_when_there_is_nothing_to_split_or_nobody_to_split_with(
    uow: UowFactory,
) -> None:
    user, trip = await going(uow, companions=["Ann"])
    await trip_cases.set_day_label(uow(), user, trip.id, date(2027, 1, 10), "Arrive", now=MADE)
    model = scripted(call("split_trip_costs"), say("Nothing to split."))
    reply = await asked(chat(uow, model), user, "split the trip costs", "tg:1:1")
    assert reply.text == "Nothing to split."  # no confirmation: the tool itself says why
    assert tool_results(model) == ["Error: there's nothing left to split on the Tokyo trip"]

    alone, _ = await going_alone(uow)
    model = scripted(call("split_trip_costs"), say("Who's going?"))
    await asked(chat(uow, model), alone, "split the trip costs", "tg:1:2")
    assert "nobody else is on the Tokyo trip yet" in tool_results(model)[0]


async def going_alone(uow: UowFactory) -> tuple[User, Trip]:
    user = await person(uow, 5353)
    return user, await trip_cases.create_trip(uow(), user, draft(companions=[]), now=MADE)


async def test_chat_notes_what_a_traveller_paid_after_asking_and_touches_no_ledger(
    uow: UowFactory,
) -> None:
    user, trip = await going(uow, companions=["Alex", "Sam"])
    model = scripted(
        call("they_paid", person="alex", amount="460", what="the ryokan"), say("Noted.")
    )
    agent = chat(uow, model)
    reply = await asked(agent, user, "alex paid 460 for the ryokan", "tg:1:1")
    assert reply.text == (
        "Note that Alex paid 460.00 SGD for the ryokan on the Tokyo trip, split evenly with "
        "everyone going? Your share, 153.34 SGD, is what you owe Alex. Nothing goes in your "
        "ledger until you settle up."
    )
    assert (await view(uow, user, trip)).paid_by_others == []
    await agent.resolve(user.id, reply.buttons[0][0].data.split(":")[1], True)
    [paid] = (await view(uow, user, trip)).paid_by_others
    assert (paid.person, paid.amount, paid.note, paid.paid_on) == (
        "Alex", sgd("460"), "the ryokan", date(2026, 9, 28),
    )  # fmt: skip
    assert tool_results(model) == [
        "Noted: Alex paid 460.00 SGD for the ryokan on the Tokyo trip, split 3 ways. "
        "You owe Alex 153.34 SGD."
    ]
    assert await ledger(uow, user) == []

    # Someone who isn't going gets a plain answer and nothing is saved.
    model = scripted(call("they_paid", person="Zoe", amount="50"), say("Add Zoe first."))
    await asked(chat(uow, model), user, "zoe paid 50", "tg:1:2")
    assert "Zoe isn't on this trip" in tool_results(model)[0]
    assert len((await view(uow, user, trip)).paid_by_others) == 1


async def test_chat_shows_who_owes_who_without_asking_and_settles_up_after_asking(
    uow: UowFactory,
) -> None:
    user, trip = await going(uow, currency="SGD")
    hotel = await spend(uow, user, "120", on_day(10), currency="SGD")
    await split_trip.split_trip_costs(uow, RATES, user, trip.id, [hotel], now=AFTER)
    await split_trip.add_paid_by_other(
        uow(), user, trip.id, person="Alex", amount=sgd("460"), note="the ryokan",
        paid_on=date(2027, 1, 11), split_with=["Sam"], now=AFTER,
    )  # fmt: skip
    model = scripted(call("settle_up", trip="tokyo"), say("Alex owes you less than you owe them."))
    reply = await asked(chat(uow, model), user, "who owes who for tokyo", "tg:1:1")
    assert reply.buttons == [] and reply.text == "Alex owes you less than you owe them."
    [lines] = tool_results(model)
    assert "You owe Alex 113.34 SGD." in lines and "Sam owes you 40.00 SGD." in lines
    assert "  Owes the user: 40.00 SGD for Shop (10 Jan)" in lines
    assert "  The user owes: 153.34 SGD for the ryokan (11 Jan)" in lines
    assert len(await ledger(uow, user)) == 1

    model = scripted(call("settle_up", person="alex"), say("Settled."))
    agent = chat(uow, model)
    ask = await asked(agent, user, "settle up with alex for tokyo", "tg:1:2")
    assert ask.text == (
        "Settle up with Alex for the Tokyo trip (You owe Alex 113.34 SGD)? This will mark Alex's "
        "40.00 SGD as paid back (recorded as money in) and settle what Alex paid (your share "
        "153.34 SGD, recorded as an expense). It records what happened; it moves no money."
    )
    assert len(await ledger(uow, user)) == 1  # nothing until they say yes
    await agent.resolve(user.id, ask.buttons[0][0].data.split(":")[1], True)
    assert tool_results(model) == [
        "Settled up with Alex for the Tokyo trip (recorded 40.00 SGD received, "
        "recorded 153.34 SGD as your share)."
    ]
    assert len(await ledger(uow, user)) == 3
    assert [b.name for b in (await view(uow, user, trip)).balances] == ["Sam"]


async def test_deleting_a_trip_takes_its_payments_with_it(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user, trip = await going(uow)
    await split_trip.add_paid_by_other(
        uow(), user, trip.id, person="Alex", amount=sgd("10"), note=None,
        paid_on=date(2027, 1, 11), split_with=None, now=AFTER,
    )  # fmt: skip
    await trip_cases.delete_trip(uow(), user.id, trip.id)
    async with engine.connect() as db:
        left: int = (
            await db.execute(text("SELECT count(*) FROM trip_paid_by_others"))
        ).scalar_one()
    assert left == 0
