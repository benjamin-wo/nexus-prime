"""Shapes the web API answers with, and the small helpers that build them."""

from collections.abc import Mapping as MappingType
from datetime import date, datetime, time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from nexus.agent.service import Reply
from nexus.application import demo as demo_cases
from nexus.application import fx
from nexus.application import wallets as wallet_cases
from nexus.channels.web.security import (
    WebRuntime,
)
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    Lineage,
    Transaction,
    User,
    Wallet,
)
from nexus.domain.money import Money


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- shapes -----------------------------------------------------------------------


class MoneyOut(Model):
    amount: str
    currency: str


def money(value: Money) -> MoneyOut:
    return MoneyOut(amount=str(value.amount), currency=value.currency)


class HomeAmountOut(Model):
    """A foreign amount in the user's home currency; amount is None if no rate was available."""

    amount: MoneyOut | None
    rate: str | None  # one unit of the original currency in the home currency
    rate_date: date | None  # the day that rate was published


class ShareOut(Model):
    name: str
    share: MoneyOut
    repaid: MoneyOut


class SplitOut(Model):
    own_share: MoneyOut  # what the bill cost the user, if everyone pays back
    people: list[ShareOut]


class LinkOut(Model):
    """The transaction on the other side of a repayment: for a bill, the money in
    that paid part of it back; for money in, the bill it paid back."""

    transaction_id: UUID
    counterparty: str | None
    occurred_at: datetime
    name: str  # who paid back
    amount: MoneyOut


class TwinOut(Model):
    """Another transaction that looks like the same payment."""

    transaction_id: UUID
    counterparty: str | None
    occurred_at: datetime
    amount: MoneyOut


class WalletRefOut(Model):
    """A wallet as a transaction names it."""

    id: UUID
    name: str
    kind: str


def wallet_ref(wallets: MappingType[UUID, Wallet], wallet_id: UUID | None) -> WalletRefOut | None:
    wallet = wallets.get(wallet_id) if wallet_id else None
    return WalletRefOut(id=wallet.id, name=wallet.name, kind=wallet.kind.value) if wallet else None


class PaidWithOut(Model):
    """The wallet an expense was paid with."""

    id: UUID
    name: str
    kind: str
    last4: str | None  # a card's last four digits, if it has them


def paid_with_ref(wallets: MappingType[UUID, Wallet], wallet_id: UUID | None) -> PaidWithOut | None:
    wallet = wallets.get(wallet_id) if wallet_id else None
    if wallet is None:
        return None
    return PaidWithOut(id=wallet.id, name=wallet.name, kind=wallet.kind.value, last4=wallet.last4)


class TransactionOut(Model):
    id: UUID
    direction: str  # "in", "out", or "move" (between two of the user's wallets)
    amount: MoneyOut
    home: HomeAmountOut | None = None  # set on listings for foreign-currency rows
    occurred_at: datetime
    counterparty: str | None
    category_id: UUID | None
    category_rule_id: UUID | None = None  # the rule that chose the category, if one did
    notes: str | None
    status: str
    source: str
    deleted: bool
    has_receipt: bool = False  # set on listings
    split: SplitOut | None = None  # a bill shared with others
    links: list[LinkOut] = []  # repayments to or from other transactions
    own: MoneyOut | None = None  # the user's own money in it, when friends paid part back
    duplicate: TwinOut | None = None  # set on listings: a possible second record of it
    # A move only: where the money left and where it went. Both null for in and out.
    from_wallet: WalletRefOut | None = None
    to_wallet: WalletRefOut | None = None
    received: MoneyOut | None = None  # a move only: what arrived, when that isn't ``amount``
    # Money out only: the wallet (a card, the main account, Cash) it was paid with; null for none.
    paid_with: PaidWithOut | None = None


def home_out(conversion: fx.Conversion) -> HomeAmountOut:
    rate = conversion.rate
    return HomeAmountOut(
        amount=money(conversion.home) if conversion.home else None,
        rate=str(rate.value) if rate else None,
        rate_date=rate.effective if rate else None,
    )


def _moved(tx: Transaction, moved: Lineage | None) -> dict[str, Any]:
    if moved is None:
        return {}
    found: dict[str, Any] = {}
    if moved.shares:
        people = [
            ShareOut(
                name=s.participant_name,
                share=money(s.share),
                repaid=money(
                    sum(
                        (
                            link.amount
                            for link in moved.links
                            if link.bill_id == tx.id and link.participant_name == s.participant_name
                        ),
                        Money.zero(s.share.currency),
                    )
                ),
            )
            for s in moved.shares
        ]
        others = sum((s.share for s in moved.shares), Money.zero(tx.amount.currency))
        found["split"] = SplitOut(own_share=money(tx.amount - others), people=people)
    links = []
    for link in moved.links:
        mine_is_bill = link.bill_id == tx.id
        links.append(
            LinkOut(
                transaction_id=link.income_id if mine_is_bill else link.bill_id,
                counterparty=None if mine_is_bill else link.bill_counterparty,
                occurred_at=link.income_occurred_at if mine_is_bill else link.bill_occurred_at,
                name=link.participant_name,
                amount=money(link.amount),
            )
        )
    found["links"] = links
    repaid = moved.repaid(tx.id)
    if repaid:
        found["own"] = money(Money(tx.amount.amount - repaid, tx.amount.currency))
    return found


def tx_out(
    tx: Transaction,
    conversion: fx.Conversion | None = None,
    *,
    has_receipt: bool = False,
    moved: Lineage | None = None,
    twin: Transaction | None = None,
    wallets: MappingType[UUID, Wallet] | None = None,
) -> TransactionOut:
    """``wallets`` names the ends of a move and what an expense was paid with; load them
    with ``_wallets_of``."""
    named = wallets or {}
    return TransactionOut(
        id=tx.id,
        direction=tx.direction.value,
        amount=money(tx.amount),
        home=home_out(conversion) if conversion else None,
        occurred_at=tx.occurred_at,
        counterparty=tx.counterparty,
        category_id=tx.category_id,
        category_rule_id=tx.category_rule_id,
        notes=tx.notes,
        status=tx.status.value,
        source=tx.source.value,
        deleted=tx.is_deleted,
        has_receipt=has_receipt,
        duplicate=TwinOut(
            transaction_id=twin.id,
            counterparty=twin.counterparty,
            occurred_at=twin.occurred_at,
            amount=money(twin.amount),
        )
        if twin
        else None,
        from_wallet=wallet_ref(named, tx.from_wallet_id),
        to_wallet=wallet_ref(named, tx.to_wallet_id),
        received=money(tx.received_amount) if tx.received_amount else None,
        paid_with=paid_with_ref(named, tx.paid_with_wallet_id),
        **_moved(tx, moved),
    )


class UserOut(Model):
    # Null for an account that signed up another way (none yet: every account has one).
    telegram_user_id: int | None
    role: str
    home_currency: str
    # Their CURRENT time zone: it follows where they are. Everything shown in their day
    # uses it.
    timezone: str
    # Where they live, the zone they go back to.
    home_timezone: str
    # What set the current zone: home, phone, chat or trip.
    timezone_source: str
    # When their phone or they last said where they are; None if never.
    timezone_set_at: datetime | None = None
    # Their Telegram name, kept at sign-in; None for someone who hasn't one.
    display_name: str | None = None
    # Whether a Telegram chat is linked, so the bot can message them (Home's "Get started"
    # guide shows it). A demo has none.
    telegram_linked: bool = False


class DemoInfoOut(Model):
    expires_at: datetime
    messages_left: int


class PreferencesOut(Model):
    # Whether the user keeps track of which card paid (off: simple mode).
    track_cards: bool
    # Whether Invest, Travel and Health show in the menu. Null: not decided (hidden; it turns on by
    # itself the first time they use it in chat). False: they turned it off.
    show_invest: bool | None
    show_travel: bool | None
    show_health: bool | None


def preferences_out(user: User) -> PreferencesOut:
    return PreferencesOut(
        track_cards=user.track_cards,
        show_invest=user.show_invest,
        show_travel=user.show_travel,
        show_health=user.show_health,
    )


class MeOut(Model):
    user: UserOut
    csrf_token: str
    preferences: PreferencesOut
    # Set by a sign-in that added the person to a trip with a trip invite.
    joined_trip: UUID | None = None
    # Set for a public-demo account: when it ends and how many chat messages it has left.
    demo: DemoInfoOut | None = None


def me_out(
    user: User,
    csrf: str,
    joined_trip: UUID | None = None,
    demo: demo_cases.DemoUsage | None = None,
) -> MeOut:
    return MeOut(
        user=UserOut(
            telegram_user_id=user.telegram_user_id,
            role=user.role.value,
            home_currency=user.home_currency,
            timezone=user.timezone,
            home_timezone=user.home_timezone,
            timezone_source=user.timezone_source.value,
            timezone_set_at=user.timezone_set_at,
            display_name=user.display_name,
            telegram_linked=user.telegram_chat_id is not None,
        ),
        preferences=preferences_out(user),
        csrf_token=csrf,
        joined_trip=joined_trip,
        demo=(
            DemoInfoOut(
                expires_at=user.demo_expires_at,
                messages_left=demo.messages_left if demo else demo_cases.MESSAGES,
            )
            if user.demo_expires_at
            else None
        ),
    )


class ButtonOut(Model):
    label: str
    data: str


class ReplyViewOut(Model):
    """A view shown with a reply (ADR 0005): what ``view.show`` carries."""

    view_id: str
    kind: str
    params: dict[str, Any]
    focus: bool
    caption: str
    summary: dict[str, Any] | None


class ReplyOut(Model):
    text: str
    buttons: list[list[ButtonOut]]
    views: list[ReplyViewOut] = Field(default_factory=list)  # empty unless views are switched on


def replies_out(replies: list[Reply]) -> list[ReplyOut]:
    return [
        ReplyOut(
            text=r.text,
            buttons=[[ButtonOut(label=b.label, data=b.data) for b in row] for row in r.buttons],
            views=[ReplyViewOut(**v.event()) for v in r.views],
        )
        for r in replies
    ]


def _tz(user: User) -> ZoneInfo:
    return ZoneInfo(user.timezone)


async def _conversions(
    web: WebRuntime, user: User, txs: list[Transaction]
) -> dict[UUID, fx.Conversion]:
    """Home-currency views of the foreign-currency rows, each at its own day's rate."""
    home, tz = user.home_currency, _tz(user)
    foreign = [(t, t.occurred_at.astimezone(tz).date()) for t in txs if t.amount.currency != home]
    found = await fx.rates_for(web.rates, home, ((t.amount.currency, d) for t, d in foreign))
    return {t.id: fx.convert(t.amount, d, home, found) for t, d in foreign}


async def _wallets_of(web: WebRuntime, user: User, txs: list[Transaction]) -> dict[UUID, Wallet]:
    """The user's wallets by id, but only when one of ``txs`` names one: a move's ends, or
    what an expense was paid with."""
    if not any(t.is_move or t.paid_with_wallet_id for t in txs):
        return {}
    return {w.id: w for w in await wallet_cases.list_wallets(web.uow(), user.id)}


async def _out(web: WebRuntime, user: User, tx: Transaction) -> TransactionOut:
    """A bare transaction (no listing extras), with its wallets if it names any."""
    return tx_out(tx, wallets=await _wallets_of(web, user, [tx]))


def _day_start(user: User, day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=_tz(user))


def _when(user: User, value: str | None, now: datetime) -> datetime:
    """A date (noon local) or full timestamp; now when absent."""
    if value is None:
        return now
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInput("dates look like 2026-09-28") from exc
    if parsed.tzinfo is not None:
        return parsed
    if parsed.time() == time() and "T" not in value:
        return datetime.combine(parsed.date(), time(12), tzinfo=_tz(user))
    return parsed.replace(tzinfo=_tz(user))
