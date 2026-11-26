"""Web API: notifications, voice, preferences and trip alerts."""

from datetime import datetime, time
from decimal import Decimal
from typing import Self
from uuid import UUID

from fastapi import APIRouter
from pydantic import model_validator

from nexus.application import messaging as message_cases
from nexus.application import notifications as notify_cases
from nexus.application import users as user_cases
from nexus.application import voice as voice_cases
from nexus.channels.web.security import (
    Auth,
    Runtime,
)
from nexus.channels.web.shapes import Model, PreferencesOut, preferences_out
from nexus.domain.notifications import (
    Frequency,
    Level,
    NotificationSettings,
    Status,
    label,
)
from nexus.domain.voice import PRESETS, VoiceSettings

router = APIRouter(prefix="/api")

# --- transaction updates on Telegram ----------------------------------------------------


class UpdatesOut(Model):
    frequency: Frequency
    daily_at: str  # HH:MM, the daily summary's time
    description: str
    options: dict[Frequency, str]
    quiet_start: str  # HH:MM, local time; the same as quiet_end means no quiet hours
    quiet_end: str
    move_alert_percent: Decimal  # a stock moving this much in a day is a big move: 1 to 20
    market_summary: bool  # the morning summary of the US market
    daily_cap: int  # messages a day before the rest wait for a digest: 3 to 20


def _updates_out(settings: NotificationSettings) -> UpdatesOut:
    return UpdatesOut(
        frequency=settings.frequency,
        daily_at=settings.daily_at.strftime("%H:%M"),
        description=notify_cases.describe(settings),
        options={f: label(f, settings.daily_at) for f in Frequency},
        quiet_start=settings.quiet_start.strftime("%H:%M"),
        quiet_end=settings.quiet_end.strftime("%H:%M"),
        move_alert_percent=settings.move_alert_percent,
        market_summary=settings.market_summary,
        daily_cap=settings.daily_cap,
    )


@router.get("/notifications")
async def notifications(auth: Auth, web: Runtime) -> UpdatesOut:
    return _updates_out(await notify_cases.get_settings(web.uow(), auth.user.id))


class UpdatesIn(Model):
    """What to change; what is left out stays as it was."""

    frequency: Frequency | None = None
    daily_at: time | None = None  # only with daily
    quiet_start: time | None = None
    quiet_end: time | None = None
    move_alert_percent: Decimal | None = None  # 1 to 20
    market_summary: bool | None = None
    daily_cap: int | None = None  # 3 to 20


@router.put("/notifications")
async def set_notifications(body: UpdatesIn, auth: Auth, web: Runtime) -> UpdatesOut:
    now = web.clock()
    updated = await notify_cases.get_settings(web.uow(), auth.user.id)
    if body.frequency is not None or body.daily_at is not None:
        updated = await notify_cases.set_frequency(
            web.uow(),
            auth.user.id,
            body.frequency or updated.frequency,
            now=now,
            daily_at=body.daily_at,
        )
    if any(
        v is not None
        for v in (
            body.quiet_start,
            body.quiet_end,
            body.move_alert_percent,
            body.market_summary,
            body.daily_cap,
        )
    ):
        updated = await notify_cases.set_market(
            web.uow(),
            auth.user.id,
            now=now,
            move_alert_percent=body.move_alert_percent,
            market_summary=body.market_summary,
            quiet_start=body.quiet_start,
            quiet_end=body.quiet_end,
            daily_cap=body.daily_cap,
        )
    return _updates_out(updated)


# --- how Nexus talks ----------------------------------------------------------------------


class VoicePresetOut(Model):
    id: str
    label: str
    blurb: str
    emoji: str  # the dials this preset starts with
    length: str
    humour: str


class VoiceOut(Model):
    preset: str
    emoji: str
    length: str
    humour: str
    note: str | None
    presets: list[VoicePresetOut]


def _voice_out(voice: VoiceSettings) -> VoiceOut:
    return VoiceOut(
        preset=voice.preset,
        emoji=voice.emoji,
        length=voice.length,
        humour=voice.humour,
        note=voice.note,
        presets=[
            VoicePresetOut(
                id=p.id, label=p.label, blurb=p.blurb, emoji=p.emoji, length=p.length,
                humour=p.humour,
            )
            for p in PRESETS
        ],
    )  # fmt: skip


@router.get("/settings/voice")
async def get_voice(auth: Auth, web: Runtime) -> VoiceOut:
    return _voice_out(await voice_cases.get_voice(web.uow(), auth.user.id))


class VoiceIn(Model):
    """What to change; what is left out stays as it was. A preset starts from its
    own emoji, length and humour unless those are given too. A note of "" or null clears it."""

    preset: str | None = None
    emoji: str | None = None
    length: str | None = None
    humour: str | None = None
    note: str | None = None


@router.put("/settings/voice")
async def set_voice(body: VoiceIn, auth: Auth, web: Runtime) -> VoiceOut:
    updated = await voice_cases.set_voice(
        web.uow(),
        auth.user.id,
        preset=body.preset,
        emoji=body.emoji,
        length=body.length,
        humour=body.humour,
        note=body.note,
        clear_note="note" in body.model_fields_set and body.note is None,
        now=web.clock(),
    )
    return _voice_out(updated)


class PreferencesIn(Model):
    track_cards: bool | None = None
    show_invest: bool | None = None
    show_travel: bool | None = None
    show_health: bool | None = None

    @model_validator(mode="after")
    def _only_what_is_sent(self) -> Self:
        """Send at least one, and not as null: only the fields sent are changed."""
        sent = self.model_fields_set
        if not sent or any(getattr(self, name) is None for name in sent):
            raise ValueError("send at least one preference, each true or false")
        return self


@router.put("/settings/preferences")
async def set_preferences(body: PreferencesIn, auth: Auth, web: Runtime) -> PreferencesOut:
    """Change the preferences sent (only those). ``track_cards``: whether to keep track of
    which card paid; off, the usual card isn't applied to new expenses, emails and imports
    don't name a card, and the assistant doesn't ask; what is stored stays, and turning it on
    again brings it back. ``show_invest``, ``show_travel`` and ``show_health``: whether
    Invest, Travel and Health show in the menu (the pages and chat work either way); setting
    one, either way, is the user's choice, so a false is never turned on by itself.
    Allowed for a demo. Returns them all."""
    user = await user_cases.set_preferences(
        web.uow(),
        auth.user.id,
        track_cards=body.track_cards,
        show_invest=body.show_invest,
        show_travel=body.show_travel,
        show_health=body.show_health,
    )
    return preferences_out(user)


class NotificationOut(Model):
    id: UUID
    kind: str
    level: Level
    text: str
    link: str | None  # a web path that opens what it is about
    status: Status
    created_at: datetime
    sent_at: datetime | None  # when it went, alone or in a digest
    held_until: datetime | None


@router.get("/notifications/history")
async def notification_history(auth: Auth, web: Runtime) -> list[NotificationOut]:
    """What Nexus meant to tell the user on Telegram in the last 30 days, newest first."""
    found = await message_cases.history(web.uow(), auth.user.id, now=web.clock())
    return [
        NotificationOut(
            id=n.id,
            kind=n.kind,
            level=n.level,
            text=n.text,
            link=n.link,
            status=n.status,
            created_at=n.created_at,
            sent_at=n.sent_at,
            held_until=n.held_until,
        )
        for n in found
    ]


# --- Telegram message when someone changes a trip the user shares ---------------------


class TripAlertsOut(Model):
    enabled: bool  # on by default


@router.get("/trip-alerts")
async def trip_alerts(auth: Auth, web: Runtime) -> TripAlertsOut:
    return TripAlertsOut(enabled=auth.user.trip_activity_alerts)


class TripAlertsIn(Model):
    enabled: bool


@router.put("/trip-alerts")
async def set_trip_alerts(body: TripAlertsIn, auth: Auth, web: Runtime) -> TripAlertsOut:
    """Whether the user is told on Telegram when someone else changes a trip they share
    (one message per trip every 30 minutes at most)."""
    async with web.uow() as uow:
        await uow.ledger.set_trip_activity_alerts(auth.user.id, body.enabled)
        await uow.commit()
    return TripAlertsOut(enabled=body.enabled)
