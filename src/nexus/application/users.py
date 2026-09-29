from dataclasses import dataclass
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nexus.application.clock import utcnow
from nexus.application.ports import LedgerRepository, UnitOfWork
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Category, Role, User, UserId
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
        cmd.telegram_user_id, currency, cmd.telegram_chat_id, cmd.timezone, cmd.role
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
    )
    created = await repo.insert_user_if_absent(candidate)
    if created:
        for name in DEFAULT_CATEGORIES:
            await repo.insert_category(
                Category(id=uuid4(), user_id=candidate.id, name=name, active=True)
            )
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


async def find_telegram_user(uow: UnitOfWork, telegram_user_id: int) -> User | None:
    async with uow:
        return await uow.ledger.get_user_by_telegram_id(telegram_user_id)
