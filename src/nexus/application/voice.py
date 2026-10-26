"""How Nexus talks to a user: reading and changing their voice (see ``domain.voice``).

Used by the settings page, the chat tools and every chat turn (which loads it once)."""

from datetime import datetime

from nexus.application.ports import UnitOfWork
from nexus.domain.ledger import UserId
from nexus.domain.voice import Emoji, Humour, Length, Preset, VoiceSettings, changed


async def get_voice(uow: UnitOfWork, user_id: UserId) -> VoiceSettings:
    """The user's voice; the default one if they never chose."""
    async with uow:
        return await uow.memory.get_voice(user_id)


async def set_voice(
    uow: UnitOfWork,
    user_id: UserId,
    *,
    preset: str | Preset | None = None,
    emoji: str | Emoji | None = None,
    length: str | Length | None = None,
    humour: str | Humour | None = None,
    note: str | None = None,
    clear_note: bool = False,
    now: datetime,
) -> VoiceSettings:
    """Change the voice; what is left out stays as it was. Choosing a preset starts from
    that preset's own dials, unless dials are given in the same call. A blank
    note clears the note, like ``clear_note``. Raises InvalidInput for a value that isn't
    one of the choices, or a note that is too long or has control characters."""
    async with uow:
        current = await uow.memory.get_voice(user_id, for_update=True)
        updated = changed(
            current,
            preset=preset,
            emoji=emoji,
            length=length,
            humour=humour,
            note=note,
            clear_note=clear_note,
        )
        await uow.memory.save_voice(user_id, updated, now)
        await uow.commit()
    return updated
