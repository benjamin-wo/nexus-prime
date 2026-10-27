"""The people the user already deals with, so a name that is nearly one of them (Anne for
Ann) is asked about rather than made into a second person."""

from collections.abc import Iterable

from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId, near_name

MAX_KNOWN = 30


async def known_people(uow: UnitOfWork, user_id: UserId) -> list[str]:
    """Names the user already uses, each once (any case), most recently used first, at
    most 30: split participants and split-habit people, trip companions, and people who
    paid for a trip."""
    async with uow:
        found = await uow.ledger.split_people(user_id, MAX_KNOWN)
        found += await uow.trips.trip_people(user_id, MAX_KNOWN)
    names: dict[str, str] = {}
    for name, _ in sorted(found, key=lambda f: f[1], reverse=True):
        names.setdefault(" ".join(name.casefold().split()), name)
    return list(names.values())[:MAX_KNOWN]


async def check_not_misspelt(uow: UnitOfWork, user_id: UserId, names: Iterable[str]) -> None:
    """Raises InvalidInput when a name is not someone the user knows but is a near miss
    for one who is: the caller asks the user, who may mean a new person."""
    wanted = [n for n in names if n.strip()]
    if not wanted:
        return
    known = await known_people(uow, user_id)
    for name in wanted:
        close = near_name(known, name)
        if close is not None:
            given = name.strip()
            raise InvalidInput(
                f"{given} would be a new person; the user already knows {close}. Ask the "
                f"user whether they mean {close}, unless they said {given} is someone new "
                "(then call again with new_person=true)."
            )
