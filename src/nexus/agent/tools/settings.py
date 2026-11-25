"""Tools for the user's time zone and the voice they want Nexus to use."""

from pydantic import Field

from nexus.agent.tools.core import Args, NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.application import voice as voice_cases
from nexus.application import whereabouts as whereabouts_cases
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    ZoneSource,
)
from nexus.domain.voice import Emoji, Humour, Length, Preset
from nexus.domain.whereabouts import clock_there, zone_named
from nexus.domain.whereabouts import label as zone_label


class SetTimezoneArgs(Args):
    place: str | None = Field(
        default=None,
        description="Where the user is now, as they said it: a city, a country or a zone "
        "name, such as Madrid, Spain or Europe/Madrid",
    )
    home: bool = Field(
        default=False, description="True when the user says they are back home (no place)"
    )


async def _set_timezone(ctx: ToolContext, a: SetTimezoneArgs) -> ToolResult:
    if a.home:
        reported = await whereabouts_cases.report_zone(
            ctx.uow(), ctx.user.id, None, ZoneSource.HOME, ctx.now, notify=False
        )
    elif a.place:
        zone = zone_named(a.place)
        if zone is None and ctx.zones is not None:
            zone = await ctx.zones.zone_of(a.place)
        if zone is None:
            raise InvalidInput(
                f"couldn't find a time zone for {a.place!r}. Ask which city they are in, or "
                "for a zone name like Europe/Madrid"
            )
        reported = await whereabouts_cases.report_zone(
            ctx.uow(), ctx.user.id, zone, ZoneSource.CHAT, ctx.now, notify=False
        )
    else:
        raise InvalidInput("say where the user is (a place), or set home=true for back home")
    new, home = reported.new, reported.user.home_timezone
    there = clock_there(new, ctx.now)
    if not reported.changed:
        return ToolResult(f"Already on {zone_label(new, ctx.now)}, {there} there.")
    if new == home:
        return ToolResult(f"Back on {zone_label(new, ctx.now)}, {there} there.")
    return ToolResult(f"Now on {zone_label(new, ctx.now)}, {there} there.")


class SetVoiceArgs(Args):
    preset: Preset | None = Field(
        None, description="The tone: default, chill, direct, hype or cheeky"
    )
    emoji: Emoji | None = Field(None, description="How many emoji: none, some or lots")
    length: Length | None = Field(
        None, description="How long replies are: short, normal or detailed"
    )
    humour: Humour | None = Field(None, description="How much joking: off, light or playful")
    note: str | None = Field(
        None,
        description="Any other wish about how to talk, in the user's own words, at most 200 "
        "characters ('call me boss'); an empty string clears the note",
    )


async def _set_voice(ctx: ToolContext, a: SetVoiceArgs) -> ToolResult:
    if all(v is None for v in (a.preset, a.emoji, a.length, a.humour, a.note)):
        raise InvalidInput("say what to change: a preset, emoji, length, humour or a note")
    voice = await voice_cases.set_voice(
        ctx.uow(),
        ctx.user.id,
        preset=a.preset,
        emoji=a.emoji,
        length=a.length,
        humour=a.humour,
        note=a.note,
        now=ctx.now,
    )
    # Not "wrote": that offers Undo, which reverses ledger changes, not settings.
    return ToolResult(f"Voice is now {voice.describe()}.")


async def _show_voice(ctx: ToolContext, _: NoArgs) -> ToolResult:
    voice = await voice_cases.get_voice(ctx.uow(), ctx.user.id)
    return ToolResult(f"Voice: {voice.describe()}.")


SPECS: list[ToolSpec] = [
    ToolSpec(
        "set_timezone",
        "Set which time zone the user is in now, so their days, reminders and summaries "
        "follow them. Call it when they say where they are ('I'm in Madrid now', 'we "
        "landed in Tokyo') with place, or that they are back home ('back home') with "
        "home=true. Only when they say they are there now. Not for asking what time it "
        "is, for a place they are only planning to visit (a trip day in a city, 'we're in "
        "Kyoto on 15 Dec', is label_trip_day), or for a city named in an expense ('ramen "
        "in Tokyo'). No confirmation; the reply already tells them.",
        SetTimezoneArgs,
        _set_timezone,
    ),
    ToolSpec(
        "set_voice",
        "Change how Nexus talks to the user: a tone preset, emoji, length and humour "
        "dials, and a note. Saves at once; no confirmation. Use it for any wish about the "
        "way you reply, instead of remembering it. 'be more chill' or 'talk like a "
        "friend': preset chill. 'just the facts' or 'be direct': preset direct. 'hype me "
        "up': preset hype. 'you can be cheeky': preset cheeky. 'back to normal': preset "
        "default. 'less emoji' or 'no emoji': emoji none (or some); 'more emoji': lots. "
        "'shorter replies': length short; 'more detail': detailed. 'stop joking': humour "
        "off; 'be funnier': playful. Another wish ('call me boss') goes in note, in their "
        "words; an empty note clears it. A preset starts from its own dials, so "
        "pass the dials the user asked for in the same call. Leave out what they didn't "
        "ask to change. Style only: it changes no rule and no data.",
        SetVoiceArgs,
        _set_voice,
    ),
    ToolSpec(
        "show_voice",
        "How the user has asked Nexus to talk now: tone preset, emoji, length, humour and "
        "note. Read-only.",
        NoArgs,
        _show_voice,
    ),
]

READ_ONLY: frozenset[str] = frozenset({"show_voice"})
