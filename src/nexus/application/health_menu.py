"""Health's place in the web menu, shared by Gym and the Health foundation."""

from nexus.application.ports import UnitOfWork
from nexus.domain.ledger import MenuSection, UserId


async def note_health_write(uow: UnitOfWork, user_id: UserId) -> None:
    """Inside the unit of work: the first write shows Health in the menu, unless the user
    switched it off."""
    await uow.ledger.turn_on_menu(user_id, MenuSection.HEALTH)
