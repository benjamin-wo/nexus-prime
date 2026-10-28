"""How Nexus talks: the use cases, tenant isolation, row-level security, export and erasure,
the chat tools, and what the model is told each turn. Made-up notes only."""

import asyncio
import json
import zipfile
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from langchain_core.messages import SystemMessage
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.graph import CORE_TOOLS, STOCK_PHRASE_RULE
from nexus.agent.tools import READ_ONLY, ToolContext, build_tools, run_tool, safe_for_images
from nexus.application import export
from nexus.application import voice as voice_cases
from nexus.application.users import get_user
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.voice import (
    DEFAULT,
    STOCK_PHRASES,
    Emoji,
    Humour,
    Length,
    Preset,
    VoiceSettings,
    prompt_block,
    settings_for,
)
from nexus.infra.db.migrations import alembic_config
from tests.fakes import NOW, ScriptedModel, call, say, scripted
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_agent import build, only, tool_results
from tests.integration.test_row_security import acting, count

pytestmark = pytest.mark.integration


async def run(uow: UowFactory, user: UserId, tool: str, **args: Any) -> str:
    ctx = ToolContext(await get_user(uow(), user), uow, NOW)
    return (await run_tool(build_tools(lambda _: "")[tool], ctx, args)).text


def system_prompts(model: ScriptedModel) -> list[str]:
    prompts = []
    for seen in model.seen:
        first = seen[0]
        assert isinstance(first, SystemMessage)
        prompts.append(str(first.content))
    return prompts


# --- use cases ------------------------------------------------------------------------------


async def test_no_row_is_the_default_voice(uow: UowFactory, alice: UserId) -> None:
    assert await voice_cases.get_voice(uow(), alice) == DEFAULT


async def test_a_voice_is_saved_and_read_back(uow: UowFactory, alice: UserId) -> None:
    saved = await voice_cases.set_voice(
        uow(), alice, preset="cheeky", emoji="none", note="  call me   boss ", now=NOW
    )
    assert saved == VoiceSettings(
        Preset.CHEEKY, Emoji.NONE, Length.SHORT, Humour.PLAYFUL, "call me boss"
    )
    assert await voice_cases.get_voice(uow(), alice) == saved


async def test_a_different_preset_resets_the_dials_unless_dials_are_given(
    uow: UowFactory, alice: UserId
) -> None:
    await voice_cases.set_voice(
        uow(), alice, preset="hype", length="detailed", note="call me boss", now=NOW
    )
    chill = await voice_cases.set_voice(uow(), alice, preset="chill", now=NOW)
    assert chill == VoiceSettings(
        Preset.CHILL, Emoji.SOME, Length.SHORT, Humour.LIGHT, "call me boss"
    )
    direct = await voice_cases.set_voice(uow(), alice, preset="direct", humour="light", now=NOW)
    assert (direct.emoji, direct.length, direct.humour) == (Emoji.NONE, Length.SHORT, Humour.LIGHT)
    assert await voice_cases.get_voice(uow(), alice) == direct


async def test_choosing_the_preset_in_use_resets_its_dials(uow: UowFactory, alice: UserId) -> None:
    await voice_cases.set_voice(uow(), alice, preset="chill", emoji="none", note="hi", now=NOW)
    again = await voice_cases.set_voice(uow(), alice, preset="chill", now=NOW)
    assert again == VoiceSettings(Preset.CHILL, Emoji.SOME, Length.SHORT, Humour.LIGHT, "hi")


async def test_a_dial_or_the_note_changes_alone(uow: UowFactory, alice: UserId) -> None:
    await voice_cases.set_voice(uow(), alice, preset="chill", now=NOW)
    again = await voice_cases.set_voice(uow(), alice, emoji="none", now=NOW)
    assert again == VoiceSettings(Preset.CHILL, Emoji.NONE, Length.SHORT, Humour.LIGHT)
    noted = await voice_cases.set_voice(uow(), alice, note="short please", now=NOW)
    assert noted.note == "short please" and noted.emoji is Emoji.NONE
    assert (await voice_cases.set_voice(uow(), alice, note="", now=NOW)).note is None
    await voice_cases.set_voice(uow(), alice, note="short please", now=NOW)
    cleared = await voice_cases.set_voice(uow(), alice, clear_note=True, now=NOW)
    assert cleared.note is None and cleared.preset is Preset.CHILL


async def test_back_to_default_is_the_default_voice_again(uow: UowFactory, alice: UserId) -> None:
    await voice_cases.set_voice(uow(), alice, preset="direct", now=NOW)
    back = await voice_cases.set_voice(uow(), alice, preset="default", now=NOW)
    assert back == DEFAULT
    assert prompt_block(await voice_cases.get_voice(uow(), alice)) == ""


async def test_a_bad_value_changes_nothing(uow: UowFactory, alice: UserId) -> None:
    kept = await voice_cases.set_voice(uow(), alice, preset="chill", now=NOW)
    refused: list[dict[str, Any]] = [
        {"preset": "grumpy"},
        {"emoji": "many"},
        {"length": "long"},
        {"humour": "silly"},
        {"note": "x" * 201},
        {"note": "bell\x07"},
        {"preset": "direct", "emoji": "many"},
    ]
    for bad in refused:
        with pytest.raises(InvalidInput):
            await voice_cases.set_voice(uow(), alice, now=NOW, **bad)
    assert await voice_cases.get_voice(uow(), alice) == kept


async def test_saving_twice_keeps_one_row(
    uow: UowFactory, alice: UserId, admin_engine: AsyncEngine
) -> None:
    await voice_cases.set_voice(uow(), alice, preset="chill", now=NOW)
    await voice_cases.set_voice(uow(), alice, preset="hype", now=NOW)
    async with admin_engine.connect() as db:
        assert await count(db, "SELECT count(*) FROM voice_settings") == 1


# --- other people's voices --------------------------------------------------------------------


async def test_one_users_voice_never_reaches_another(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await voice_cases.set_voice(uow(), alice, preset="cheeky", note="call me boss", now=NOW)
    assert await voice_cases.get_voice(uow(), bob) == DEFAULT
    await voice_cases.set_voice(uow(), bob, preset="direct", now=NOW)
    assert (await voice_cases.get_voice(uow(), alice)).preset is Preset.CHEEKY
    assert (await voice_cases.get_voice(uow(), bob)).note is None
    assert "boss" not in await run(uow, bob, "show_voice")


async def test_row_level_security_hides_and_protects_voices(
    engine: AsyncEngine, uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await voice_cases.set_voice(uow(), alice, preset="cheeky", now=NOW)
    await voice_cases.set_voice(uow(), bob, preset="direct", now=NOW)
    async with acting(engine, alice) as db:
        assert await count(db, "SELECT count(*) FROM voice_settings") == 1
    async with acting(engine, None) as db:  # a background job names nobody
        assert await count(db, "SELECT count(*) FROM voice_settings") == 2

    async with acting(engine, bob) as db:
        gone = await db.execute(text("DELETE FROM voice_settings WHERE user_id = :u"), {"u": alice})
        assert gone.rowcount == 0
        changed = await db.execute(
            text("UPDATE voice_settings SET preset = 'hype' WHERE user_id = :u"), {"u": alice}
        )
        assert changed.rowcount == 0
    async with acting(engine, bob) as db:
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.execute(
                text("UPDATE voice_settings SET user_id = :alice WHERE user_id = :bob"),
                {"alice": alice, "bob": bob},
            )
    carol = uuid4()
    async with acting(engine, bob) as db:
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.execute(
                text(
                    "INSERT INTO voice_settings (user_id, preset, emoji, length, humour, "
                    "updated_at) VALUES (:u, 'chill', 'some', 'short', 'light', now())"
                ),
                {"u": carol},
            )
    assert (await voice_cases.get_voice(uow(), alice)).preset is Preset.CHEEKY


async def test_the_database_keeps_to_the_choices_and_a_short_note(
    admin_engine: AsyncEngine, uow: UowFactory, alice: UserId
) -> None:
    good = {"preset": "chill", "emoji": "some", "length": "short", "humour": "light", "note": None}
    bad = [
        ("preset", "grumpy", "ck_voice_settings_preset"),
        ("emoji", "many", "ck_voice_settings_emoji"),
        ("length", "long", "ck_voice_settings_length"),
        ("humour", "silly", "ck_voice_settings_humour"),
        ("note", "x" * 201, "ck_voice_settings_note_length"),
        ("note", "", "ck_voice_settings_note_length"),
    ]
    for column, value, constraint in bad:
        with pytest.raises(DBAPIError, match=constraint):
            async with admin_engine.begin() as db:
                await db.execute(
                    text(
                        "INSERT INTO voice_settings (user_id, preset, emoji, length, humour, "
                        "note, updated_at) VALUES (:user_id, :preset, :emoji, :length, "
                        ":humour, :note, now())"
                    ),
                    {"user_id": alice, **good, column: value},
                )
    async with admin_engine.connect() as db:
        assert await count(db, "SELECT count(*) FROM voice_settings") == 0


# --- export and erasure -----------------------------------------------------------------------


async def test_a_voice_is_exported_and_erased_with_its_owner(
    uow: UowFactory, alice: UserId, bob: UserId, admin_engine: AsyncEngine
) -> None:
    await voice_cases.set_voice(uow(), alice, preset="chill", note="call me boss", now=NOW)
    await voice_cases.set_voice(uow(), bob, preset="direct", note="no pleasantries", now=NOW)

    file = await export.build_export(
        uow, None, await get_user(uow(), alice), ledger_csv="", now=NOW
    )
    archive = zipfile.ZipFile(file)
    exported = json.loads(archive.read("voice.json"))["voice"]
    assert {k: exported[k] for k in ("preset", "emoji", "length", "humour", "note")} == {
        "preset": "chill",
        "emoji": "some",
        "length": "short",
        "humour": "light",
        "note": "call me boss",
    }
    assert exported["user_id"] == str(alice)
    assert "pleasantries" not in archive.read("voice.json").decode()
    assert "voice.json" in archive.read("README.txt").decode()
    file.close()

    async with uow() as tx:
        await tx.user_data.erase(alice, chat_thread="tg:alice")
        await tx.commit()
    async with admin_engine.connect() as db:
        rows = (await db.execute(text("SELECT user_id FROM voice_settings"))).all()
    assert [r.user_id for r in rows] == [bob]
    assert (await voice_cases.get_voice(uow(), bob)).note == "no pleasantries"


async def test_a_user_with_no_voice_exports_none(uow: UowFactory, alice: UserId) -> None:
    file = await export.build_export(
        uow, None, await get_user(uow(), alice), ledger_csv="", now=NOW
    )
    assert json.loads(zipfile.ZipFile(file).read("voice.json")) == {"voice": None}
    file.close()


# --- the chat tools ---------------------------------------------------------------------------


def test_the_voice_tools_are_always_offered_and_never_ask() -> None:
    tools = build_tools(lambda _: "")
    assert "set_voice" in CORE_TOOLS and "show_voice" in CORE_TOOLS
    assert tools["set_voice"].confirm is None and tools["show_voice"].confirm is None
    # Only reading is allowed on a turn about a photo the user didn't ask to act on.
    assert "show_voice" in READ_ONLY and "set_voice" not in READ_ONLY
    assert safe_for_images(tools["show_voice"]) and not safe_for_images(tools["set_voice"])


def test_the_tool_schema_offers_only_the_real_choices() -> None:
    spec = build_tools(lambda _: "")["set_voice"]
    properties = spec.schema()["function"]["parameters"]["properties"]

    def choices(name: str) -> list[str]:
        [options] = [o["enum"] for o in properties[name]["anyOf"] if "enum" in o]
        return list(options)

    assert choices("preset") == [p.value for p in Preset]
    assert choices("emoji") == [e.value for e in Emoji]
    assert choices("length") == [x.value for x in Length]
    assert choices("humour") == [h.value for h in Humour]
    assert "note" in properties
    for ask in ("be more chill", "less emoji", "shorter replies", "stop joking", "back to normal"):
        assert ask in spec.description


async def test_set_voice_saves_at_once_and_says_what_it_is_now(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(call("set_voice", preset="chill"), say("Done."))
    reply = only(await build(uow, model).handle_text(alice, "be more chill", "t"))
    assert reply.text == "Done." and not reply.buttons
    assert await voice_cases.get_voice(uow(), alice) == settings_for(Preset.CHILL)
    assert tool_results(model) == [
        "Voice is now preset chill (Chill friend), emoji some, length short, humour light, no note."
    ]


async def test_each_casual_ask_maps_to_its_setting(uow: UowFactory, alice: UserId) -> None:
    assert "emoji none" in await run(uow, alice, "set_voice", emoji="none")
    assert "length short" in await run(uow, alice, "set_voice", length="short")
    assert "humour off" in await run(uow, alice, "set_voice", humour="off")
    voice = await voice_cases.get_voice(uow(), alice)
    assert (voice.preset, voice.emoji, voice.length, voice.humour) == (
        Preset.DEFAULT,
        Emoji.NONE,
        Length.SHORT,
        Humour.OFF,
    )
    back = await run(uow, alice, "set_voice", preset="default")
    assert "preset default (Default), emoji some, length normal, humour light" in back
    assert await voice_cases.get_voice(uow(), alice) == DEFAULT


async def test_set_voice_takes_a_note_and_clears_it(uow: UowFactory, alice: UserId) -> None:
    said = await run(uow, alice, "set_voice", note="call me boss")
    assert said.endswith("note: call me boss.")
    assert (await voice_cases.get_voice(uow(), alice)).note == "call me boss"
    assert "no note" in await run(uow, alice, "set_voice", note="")
    assert (await voice_cases.get_voice(uow(), alice)).note is None


async def test_set_voice_refuses_bad_values_and_empty_calls(uow: UowFactory, alice: UserId) -> None:
    await run(uow, alice, "set_voice", preset="chill")
    for args in (
        {"preset": "grumpy"},
        {"emoji": "tons"},
        {"note": "x" * 201},
        {"note": "bell\x07"},
        {},
    ):
        assert (await run(uow, alice, "set_voice", **args)).startswith("Error"), args
    assert await voice_cases.get_voice(uow(), alice) == settings_for(Preset.CHILL)


async def test_show_voice_reads_without_changing_anything(uow: UowFactory, alice: UserId) -> None:
    assert await run(uow, alice, "show_voice") == (
        "Voice: preset default (Default), emoji some, length normal, humour light, no note."
    )
    await voice_cases.set_voice(uow(), alice, preset="direct", note="call me boss", now=NOW)
    assert await run(uow, alice, "show_voice") == (
        "Voice: preset direct (Straight to the point), emoji none, length short, humour off, "
        "note: call me boss."
    )


async def test_the_model_cannot_set_another_users_voice(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    model = scripted(call("set_voice", preset="hype", user_id=str(bob)), say("Done."))
    await build(uow, model).handle_text(alice, "hype me up", "t")
    assert (await voice_cases.get_voice(uow(), alice)).preset is Preset.HYPE
    assert await voice_cases.get_voice(uow(), bob) == DEFAULT


# --- what the model is told -------------------------------------------------------------------


async def test_a_default_user_is_told_nothing_about_a_voice(uow: UowFactory, alice: UserId) -> None:
    model = scripted(say("Hi."))
    await build(uow, model).handle_text(alice, "hello", "t")
    [prompt] = system_prompts(model)
    assert "How you talk" not in prompt
    assert prompt_block(DEFAULT) == ""
    # The stock-phrase rule is there for the default voice too, inside the reply style rules.
    assert 'Never say "Fair enough", "Certainly"' in prompt
    assert 'or "Absolutely", at the start' in prompt
    assert all(f'"{phrase}"' in prompt for phrase in STOCK_PHRASES)
    assert (
        'since a plain "yes" would act on it. ' + STOCK_PHRASE_RULE + "Never show transaction ids."
    ) in prompt


async def test_the_prompt_makes_voice_settings_the_one_home_for_reply_style(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(say("Hi."))
    await build(uow, model).handle_text(alice, "hello", "t")
    [prompt] = system_prompts(model)
    assert "A reply style the user has asked for" in prompt
    assert "save it with set_voice, not only as something remembered" in prompt
    assert 'A one-off ("keep this one short") applies to that reply only.' in prompt
    assert "The reply style is the voice block below" in prompt
    assert "style preference that disagrees with it is old: ignore it" in prompt
    assert "How to reply (length, emoji, tone, humour) is not a memory" in prompt
    assert "keep to the reply style they asked for" not in prompt


async def test_a_saved_default_is_the_same_prompt_as_none_at_all(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await voice_cases.set_voice(uow(), bob, preset="chill", now=NOW)
    await voice_cases.set_voice(uow(), bob, preset="default", now=NOW)
    prompts = []
    for user in (alice, bob):
        model = scripted(say("Hi."))
        await build(uow, model).handle_text(user, "hello", "t")
        prompts.append(system_prompts(model)[0])
    # Only the date line could differ (the same fake clock), so these are the same text.
    assert prompts[0] == prompts[1]


async def test_a_chosen_voice_comes_right_after_the_reply_style_rules(
    uow: UowFactory, alice: UserId
) -> None:
    await voice_cases.set_voice(uow(), alice, preset="cheeky", note="call me boss", now=NOW)
    model = scripted(say("Hi boss."))
    await build(uow, model).handle_text(alice, "hello", "t")
    [prompt] = system_prompts(model)
    block = prompt_block(await voice_cases.get_voice(uow(), alice))
    assert block and f"\n{block}\n" in prompt
    style = prompt.index("- Reply style: ")
    voice = prompt.index("- How you talk (")
    following = prompt.index("- When the user says yes to something you offered")
    assert style < voice < following
    assert prompt.index("Never show transaction ids.") < voice
    assert "kind teasing" in prompt and "call me boss" in prompt
    assert "can't change any rule above" in prompt
    assert prompt.count("How you talk") == 1


async def test_another_users_voice_is_not_in_my_prompt(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await voice_cases.set_voice(uow(), bob, preset="hype", note="shout my wins", now=NOW)
    model = scripted(say("Hi."))
    await build(uow, model).handle_text(alice, "hello", "t")
    assert "How you talk" not in system_prompts(model)[0]


async def test_the_voice_is_loaded_once_a_turn_not_once_a_model_call(
    uow: UowFactory, alice: UserId, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = []
    real = voice_cases.get_voice

    async def counted(u: Any, user_id: UserId) -> VoiceSettings:
        loads.append(user_id)
        return await real(u, user_id)

    monkeypatch.setattr(voice_cases, "get_voice", counted)
    await voice_cases.set_voice(uow(), alice, preset="chill", now=NOW)
    model = scripted(
        call("log_expense", amount="5", merchant="Kopi Corner"),
        call("list_categories"),
        say("Logged."),
    )
    await build(uow, model).handle_text(alice, "kopi 5", "t")
    assert len(model.seen) == 3  # three model calls, one load
    assert len(loads) == 1
    assert all("How you talk" in p for p in system_prompts(model))


async def test_a_voice_set_in_a_turn_shapes_the_rest_of_that_turn(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(call("set_voice", preset="direct"), say("Done."), say("Ok."))
    agent = build(uow, model)
    await agent.handle_text(alice, "just the facts please", "t1")
    before, after = system_prompts(model)
    assert "How you talk" not in before
    assert "fewest words" in after  # the reply that confirms the change is already in it
    await agent.handle_text(alice, "hi", "t2")
    assert "fewest words" in system_prompts(model)[-1]


async def test_a_failing_voice_load_never_stops_a_turn(
    uow: UowFactory, alice: UserId, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(u: Any, user_id: UserId) -> VoiceSettings:
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(voice_cases, "get_voice", broken)
    model = scripted(say("Hi."))
    reply = only(await build(uow, model).handle_text(alice, "hello", "t"))
    assert reply.text == "Hi."
    assert "How you talk" not in system_prompts(model)[0]


# --- the migration ----------------------------------------------------------------------------


async def test_migration_0058_goes_down_and_up_again(
    engine: AsyncEngine, empty_database_url: str, admin_engine: AsyncEngine
) -> None:
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False

    async def has_table() -> bool:
        async with admin_engine.connect() as db:
            return bool(
                (await db.execute(text("SELECT to_regclass('public.voice_settings')"))).scalar()
            )

    assert await has_table()
    await asyncio.to_thread(command.downgrade, config, "0057")
    assert not await has_table()
    await upgrade(empty_database_url)
    assert await has_table()
