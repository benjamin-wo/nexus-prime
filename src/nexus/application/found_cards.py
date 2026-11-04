"""Cards a bank's email shows, for a user's wallets.

An email that says which card paid (its last four digits, and the bank by its sender's
domain) is matched to one of the user's card wallets, but only for a user who tracks which
card paid (``track_cards``):

- A card they have: the expense is tagged with it. When several cards end in the same four
  digits, the one whose issuer is the bank's; if that is still not one card, nothing is tagged.
- A card they don't have: a card wallet is added ("UOB card"), the expense is tagged with it,
  and the user is told once on Telegram, with Keep and Remove buttons. The user's row is
  locked while this is decided, so two emails arriving together add the card once.
- For a user who doesn't track cards, nothing is matched or added; they are asked once whether
  to turn it on. Either answer, or choosing the setting themselves, means they are not asked
  again.

The sender's domain is only a label here, never a reason to trust an email.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from nexus.application import users
from nexus.application import wallets as wallet_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.ports import LedgerQuery, UnitOfWork
from nexus.domain.errors import Conflict, InvalidInput, NotFound
from nexus.domain.ledger import Source, User, UserId, Wallet, WalletKind
from nexus.domain.notifications import Kind, Level
from nexus.domain.wallets import card_with_last4, cards_with_last4

type UowFactory = Callable[[], UnitOfWork]

# Button data (Telegram allows 64 bytes): ``card:keep:<wallet id>``, ``card:remove:<wallet id>``
# and, for the question about tracking, ``card:track:on`` and ``card:track:no``.
PREFIX = "card:"
KEEP = "card:keep:"
REMOVE = "card:remove:"
TRACK_ON = "card:track:on"
TRACK_NO = "card:track:no"

ASK_TRACKING = "Your bank emails show which card paid. Turn on card tracking?"
DOTS = "··"


def card_label(issuer: str | None, last4: str) -> str:
    """ "UOB ·· 1234", or "Card ·· 1234" when the bank isn't known."""
    return f"{issuer or 'Card'} {DOTS} {last4}"


def _free_name(wallets: list[Wallet], issuer: str | None, last4: str) -> str:
    """ "UOB card"; if taken (any case), "UOB card ·· 1234"; then numbered. With no known bank,
    "Card ·· 1234" (which already names the digits), then numbered."""
    taken = {w.name.casefold() for w in wallets}
    tries = [f"{issuer} card", f"{issuer} card {DOTS} {last4}"] if issuer else []
    tries = tries or [card_label(None, last4)]
    for name in tries:
        if name.casefold() not in taken:
            return name
    base = tries[-1]
    n = 2
    while f"{base} {n}".casefold() in taken:
        n += 1
    return f"{base} {n}"


async def card_for(
    uow: UowFactory,
    user_id: UserId,
    last4: str | None,
    issuer: str | None,
    *,
    now: datetime,
) -> UUID | None:
    """The card wallet an email's card is, to tag the expense with; None to tag nothing.

    Tracking on: the user's card with these digits (and issuer, if several share them), or a
    new one added and announced. Tracking off: None, and (once) the question about turning it
    on. A demo user has no email, so is ignored."""
    if not last4:
        return None
    async with uow() as tx:
        # The lock is the race guard: a second email for the same new card waits here, then
        # finds the card the first one added.
        user = await tx.ledger.get_user(user_id, for_update=True)
        if user is None or user.is_demo:
            return None
        if not user.track_cards:
            await _ask_to_track(tx, user, now)
            return None
        wallets = await tx.ledger.list_wallets(user_id)
        if cards_with_last4(wallets, last4):
            found = card_with_last4(wallets, last4, issuer)
            return found.id if found else None
        card = wallet_cases.build_wallet(
            user_id,
            _free_name(wallets, issuer, last4),
            WalletKind.CARD,
            issuer=issuer,
            last4=last4,
        )
        try:
            await tx.ledger.insert_wallet(card)
        except Conflict:  # a wallet of that name appeared meanwhile: tag nothing
            return None
        await tx.jobs.enqueue(
            TELEGRAM_SEND,
            {
                "user_id": str(user_id),
                "text": f"Found a new card: {card_label(issuer, last4)}. I've added it to Wallets.",
                "buttons": [
                    [
                        {"label": "Keep", "data": f"{KEEP}{card.id}"},
                        {"label": "Remove", "data": f"{REMOVE}{card.id}"},
                    ]
                ],
                "kind": Kind.CARD_FOUND,
                "level": Level.NOW,
                "link": "/settings/wallets",
            },
            dedupe_key=f"card.found:{card.id}",
            run_at=now,
        )
        await tx.commit()
        return card.id


async def _ask_to_track(tx: UnitOfWork, user: User, now: datetime) -> None:
    """Ask, once, whether to track which card paid. Marked as asked as it is queued (under
    the caller's lock on the user), so it is one question however many emails arrive; a user
    with no Telegram chat to ask is left for later."""
    if user.card_tracking_asked or user.telegram_chat_id is None:
        return
    await tx.ledger.set_card_tracking_asked(user.id)
    await tx.jobs.enqueue(
        TELEGRAM_SEND,
        {
            "user_id": str(user.id),
            "text": ASK_TRACKING,
            "buttons": [
                [
                    {"label": "Turn on", "data": TRACK_ON},
                    {"label": "No thanks", "data": TRACK_NO},
                ]
            ],
            "kind": Kind.CARD_TRACKING,
            "level": Level.NOW,
            "link": "/settings",
        },
        dedupe_key=f"card.track:{user.id}",
        run_at=now,
    )
    await tx.commit()


async def turn_on_tracking(uow: UnitOfWork, actor: UserId) -> None:
    """The answer Turn on. Only what comes next is affected: expenses already logged are not
    tagged with a card afterwards."""
    await users.set_track_cards(uow, actor, True)


async def decline_tracking(uow: UnitOfWork, actor: UserId) -> None:
    """The answer No thanks: never asked again. The preference itself is left as it is (the
    user may have turned it on since the question was sent)."""
    async with uow:
        await uow.ledger.set_card_tracking_asked(actor)
        await uow.commit()


@dataclass(frozen=True, slots=True)
class Removed:
    wallet: Wallet
    untagged: int  # expenses that no longer say which card paid


async def remove_found_card(uow: UowFactory, actor: UserId, wallet_id: UUID) -> Removed:
    """Remove a card that was added from an email, if that is safe: nothing but expenses
    logged from email refers to it (no move, scheduled payment or expense from anywhere else,
    and it isn't the usual card). Those expenses stop naming a card (the wallet's foreign
    key clears them). Raises NotFound if it is already gone, InvalidInput if it can't be
    removed safely."""
    async with uow() as tx:
        user = await tx.ledger.get_user(actor, for_update=True)
        wallet = await tx.ledger.get_wallet(actor, wallet_id)
        if user is None or wallet is None:
            raise NotFound("that card is already gone")
        if wallet.kind is not WalletKind.CARD:
            raise InvalidInput("that isn't a card")
        used = LedgerQuery(paid_with_wallet_id=wallet.id, include_deleted=True, limit=1)
        everything = (await tx.ledger.list_transactions(actor, used)).total
        from_email = (
            await tx.ledger.list_transactions(actor, replace(used, source=Source.EMAIL))
        ).total
        if (
            user.usual_card_wallet_id == wallet.id
            or everything != from_email
            or await tx.ledger.count_moves(actor, wallet.id) > 0
            or await tx.planning.count_bills_for_wallet(actor, wallet.id) > 0
        ):
            raise InvalidInput("that card is used by more than the emails that found it")
        await tx.planning.repoint_bills(actor, wallet.id, None)  # archived ones still name it
        await tx.ledger.delete_wallet(actor, wallet.id)
        await tx.commit()
    return Removed(wallet, everything)
