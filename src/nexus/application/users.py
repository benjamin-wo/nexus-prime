from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nexus.application.clock import utcnow
from nexus.application.ports import LedgerRepository, UnitOfWork
from nexus.application.wallets import new_cash_wallet, new_spending_wallet
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Category, MenuSection, Role, User, UserId
from nexus.domain.money import Money

DEFAULT_CATEGORIES = (
    "Dining Out",
    "Groceries",
    "Transport",
    "Shopping",
    "Bills & Utilities",
    "Socialising",
    "Health",
    "Travel",
    "Activities",
    "Subscriptions & Software",
    "Income",
    "Other",
)


@dataclass(frozen=True, slots=True)
class RegisterUser:
    telegram_user_id: int
    home_currency: str
    telegram_chat_id: int | None = None
    timezone: str = "UTC"
    role: Role = Role.MEMBER
    demo_expires_at: datetime | None = None  # a public-demo account, until this moment


@dataclass(frozen=True, slots=True)
class Registration:
    user: User
    created: bool


def _validated(cmd: RegisterUser) -> RegisterUser:
    try:
        ZoneInfo(cmd.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidInput(f"unknown timezone {cmd.timezone!r}") from exc
    currency = Money.zero(cmd.home_currency.strip().upper()).currency
    return RegisterUser(
        cmd.telegram_user_id,
        currency,
        cmd.telegram_chat_id,
        cmd.timezone,
        cmd.role,
        cmd.demo_expires_at,
    )


async def ensure_user(repo: LedgerRepository, cmd: RegisterUser) -> Registration:
    """Get or create, inside the caller's unit of work."""
    cmd = _validated(cmd)
    candidate = User(
        id=UserId(uuid4()),
        telegram_user_id=cmd.telegram_user_id,
        telegram_chat_id=cmd.telegram_chat_id,
        timezone=cmd.timezone,
        home_currency=cmd.home_currency,
        role=cmd.role,
        created_at=utcnow(),
        demo_expires_at=cmd.demo_expires_at,
    )
    created = await repo.insert_user_if_absent(candidate)
    if created:
        for name in DEFAULT_CATEGORIES:
            await repo.insert_category(Category(id=uuid4(), user_id=candidate.id, name=name))
        await repo.insert_wallet(new_spending_wallet(candidate.id))
        await repo.insert_wallet(new_cash_wallet(candidate.id))
    user = await repo.get_user_by_telegram_id(cmd.telegram_user_id)
    if user is None:  # pragma: no cover - the row was just inserted or already existed
        raise RuntimeError("user vanished during registration")
    return Registration(user, created)


async def register_user(uow: UnitOfWork, cmd: RegisterUser) -> Registration:
    """Get or create the user for a Telegram account. Safe to call on every update."""
    _validated(cmd)
    async with uow:
        registration = await ensure_user(uow.ledger, cmd)
        await uow.commit()
    return registration


async def get_user(uow: UnitOfWork, actor: UserId) -> User:
    async with uow:
        user = await uow.ledger.get_user(actor)
    if user is None:
        raise NotFound("user not found")
    return user


async def set_track_cards(uow: UnitOfWork, actor: UserId, on: bool) -> bool:
    """Turn on or off keeping track of which card paid. Off, the usual card is not applied
    to new expenses, emails and imports don't name a card, and the assistant doesn't ask.
    Nothing stored is changed, so turning it on again brings it all back. Choosing, either
    way, also means they are never asked about it (see ``found_cards``)."""
    async with uow:
        await uow.ledger.set_track_cards(actor, on)
        await uow.ledger.set_card_tracking_asked(actor)
        await uow.commit()
    return on


async def set_preferences(
    uow: UnitOfWork,
    actor: UserId,
    *,
    track_cards: bool | None = None,
    show_invest: bool | None = None,
    show_travel: bool | None = None,
) -> User:
    """Change the preferences sent, and only those (None: leave it). Choosing a menu section
    either way is the user's own say: a False sticks, and nothing turns it on by itself
    afterwards. Returns the user as they now are."""
    async with uow:
        if track_cards is not None:
            await uow.ledger.set_track_cards(actor, track_cards)
            await uow.ledger.set_card_tracking_asked(actor)
        await uow.ledger.set_menu(actor, invest=show_invest, travel=show_travel)
        user = await uow.ledger.get_user(actor)
        await uow.commit()
    if user is None:
        raise NotFound("user not found")
    return user


async def turn_on_menu(uow: UnitOfWork, actor: UserId, section: MenuSection) -> bool:
    """Show Invest or Travel in the menu because the user used it in chat, if they have not
    decided: only a null turns on, so a False (their own choice) stays off. True if it turned
    on now, which is when the reply says so (once)."""
    async with uow:
        turned = await uow.ledger.turn_on_menu(actor, section)
        await uow.commit()
    return turned


async def find_telegram_user(uow: UnitOfWork, telegram_user_id: int) -> User | None:
    async with uow:
        return await uow.ledger.get_user_by_telegram_id(telegram_user_id)
