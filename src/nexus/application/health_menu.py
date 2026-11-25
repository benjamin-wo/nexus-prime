"""Health's place in the web menu, shared by Gym and the Health foundation."""

from typing import TYPE_CHECKING

from nexus.application.ports import UnitOfWork
from nexus.domain.ledger import MenuSection, UserId

if TYPE_CHECKING:
    from nexus.agent.service import Button

HEALTH_ON_DATA = "health:on"
HEALTH_ON_LABEL = "Turn on Health"


def health_on_button() -> "Button":
    """The one-tap button for a reply that says Health is off. Pressing it runs ``turn_on``."""
    from nexus.agent.service import Button

    return Button(HEALTH_ON_LABEL, HEALTH_ON_DATA)


async def note_health_write(uow: UnitOfWork, user_id: UserId) -> None:
    """Inside the unit of work: the first write shows Health in the menu, unless the user
    switched it off."""
    await uow.ledger.turn_on_menu(user_id, MenuSection.HEALTH)
