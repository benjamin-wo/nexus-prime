"""What code enforces about How Nexus talks, as opposed to what the model is asked: the
prompt for a chosen voice (and the default's, unchanged), no emoji on any reply for a user
who chose none, and the fixed messages worded per preset. Made-up data only."""

import hashlib
from datetime import date
from typing import Any

import pytest

from nexus.agent.graph import ABOUT_THE_USER
from nexus.application import salary as salary_cases
from nexus.application import voice as voice_cases
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import list_ledger
from nexus.application.users import get_user
from nexus.domain.emoji import strip_emoji
from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from nexus.domain.planning import PayRule
from nexus.domain.voice import EXAMPLES, Preset, reminder, settings_for
from tests.fakes import NOW, call, say, scripted
from tests.integration.conftest import UowFactory, make_user
from tests.integration.test_agent import build, only
from tests.integration.test_voice import system_prompts

pytestmark = pytest.mark.integration

# The default user's prompt up to "About this user and now:", as it was before a voice could
# outweigh the persona. Providers cache a request only up to its first difference from an
# earlier one, so this text must stay the same for everyone on the default voice. Change it
# on purpose only (and know that it invalidates every cached prefix). Last changed by the
# rename of the assistant to Nexus ("Kaya" became "Nexus", "a personal finance assistant"
# became "an AI lifestyle manager"; the two are the only differences from the text before).
# Changed again by the money-arithmetic rule ("Money arithmetic only through month_outlook or
# calculate", 718 characters, after the first rule) and by the cashflow skill's line in the skill
# index (its description and tools, 169 characters, now naming leeway, left to spend and
# month_outlook): taking those two out gives the text before, hash 833626db... (13513).
# Then the rule was sharpened after live evals (a plain "1.8k for a new laptop" must be logged,
# not weighed; a month's net, past ones too; restate the figure on a correction): 72858f9b...
# (14400) became the text below, the rule's wording being the only difference.
DEFAULT_PREFIX_SHA256 = "3b544a176da1f06be1a8f2bd00b6871299109fb8e1140701f70e7d08bb13ac12"
DEFAULT_PREFIX_LENGTH = 14678


def prefix_of(prompt: str) -> str:
    return prompt.split(f"\n\n{ABOUT_THE_USER}\n")[0]


async def prompt_for(uow: UowFactory, user: UserId, **voice: Any) -> str:
    if voice:
        await voice_cases.set_voice(uow(), user, now=NOW, **voice)
    model = scripted(say("Hi."))
    await build(uow, model).handle_text(user, "hello", "t")
    [prompt] = system_prompts(model)
    return prompt


def without_reminder(prompt: str) -> str:
    """The prompt less its last paragraph, when that is a chosen voice's reminder."""
    head, _, last = prompt.rstrip().rpartition("\n\n")
    return head if last.startswith("Reply in the user's chosen voice") else prompt


def name(voice: dict[str, Any]) -> str:
    return "-".join(f"{k}={v}" for k, v in voice.items())


NON_DEFAULT: list[dict[str, Any]] = [
    {"preset": "chill"},
    {"preset": "direct"},
    {"preset": "hype"},
    {"preset": "cheeky"},
    {"emoji": "none"},
    {"note": "call me boss"},
]


# --- the prompt -------------------------------------------------------------------------------


async def test_the_default_prompt_is_byte_for_byte_what_it_was(
    uow: UowFactory, alice: UserId
) -> None:
    prompt = await prompt_for(uow, alice)
    prefix = prefix_of(prompt)
    assert len(prefix) == DEFAULT_PREFIX_LENGTH
    assert hashlib.sha256(prefix.encode()).hexdigest() == DEFAULT_PREFIX_SHA256
    assert prompt.startswith("You are Nexus, an AI lifestyle manager chatting on a phone: a")
    assert "a light touch of humour when it fits" in prompt
    assert '"4.50 at Kopi Corner ✅"' in prompt
    assert "(✅ done, ⚠️ near a limit, 🎉 a win)" in prompt
    assert "Money arithmetic only through month_outlook or calculate" in prompt
    # Nothing is added for this user, at the end either: the prompt ends at the clock.
    assert "Reply in the user's chosen voice" not in prompt
    assert prompt.splitlines()[-1].startswith("Now: ")


@pytest.mark.parametrize("voice", NON_DEFAULT, ids=name)
async def test_a_chosen_voice_gets_a_neutral_persona_and_no_emoji_examples(
    uow: UowFactory, alice: UserId, voice: dict[str, Any]
) -> None:
    prompt = await prompt_for(uow, alice, **voice)
    for gone in (
        "warm, sharp friend",
        "light touch of humour",
        "glad about wins",
        "text like a friend",
    ):
        assert gone not in prefix_of(prompt), gone  # the fixed rules, before the user's part
    # Not one emoji anywhere in it, bar the end paragraph's example replies (which are in the
    # preset's own voice and follow its emoji dial).
    assert strip_emoji(without_reminder(prompt)) == without_reminder(prompt)
    assert prompt.startswith("You are Nexus, an AI lifestyle manager chatting on a phone. ")
    assert '"4.50 at Kopi Corner"' in prompt
    assert "Emoji only as the voice block allows" in prompt
    assert prompt.count("How you talk") == 1
    assert "Money arithmetic only through month_outlook or calculate" in prompt  # every voice


@pytest.mark.parametrize("voice", NON_DEFAULT, ids=name)
async def test_a_chosen_voice_keeps_every_rule_but_the_tone_word_for_word(
    uow: UowFactory, alice: UserId, voice: dict[str, Any]
) -> None:
    default = await prompt_for(uow, alice)
    chosen = await prompt_for(uow, alice, **voice)

    def rules(prompt: str) -> tuple[str, str, str]:
        """The rules before Reply style, the style rules between its two tone parts, and the
        rest of the fixed prefix: everything but the persona and the two tone parts."""
        body = prefix_of(prompt).split("Rules:\n", 1)[1]
        before, style = body.split("- Reply style: ", 1)
        style = style.split("Don't explain ", 1)[1]
        middle, rest = style.split("addresses unless asked. ", 1)
        after = rest.split("When there's one clearly ", 1)[1]
        return before, middle, after

    assert rules(chosen) == rules(default)
    for rule in (
        "You never move money",
        "record it with log_move, which asks the user to confirm",
        "You can't export or delete all of someone's data or their account.",
        "Never log, record or change anything from an image unless",
        "Never invent transactions, amounts, dates or results",
    ):
        assert rule in chosen, rule


async def test_the_chosen_voice_is_repeated_as_the_last_paragraph(
    uow: UowFactory, alice: UserId
) -> None:
    prompt = await prompt_for(uow, alice, preset="direct")
    reminder = prompt.rstrip().split("\n\n")[-1]
    assert reminder == (
        "Reply in the user's chosen voice: straight to the point: the fewest words that "
        "answer it, no chit-chat, no reactions, no pleasantries, no emoji. "
        "Emoji: none at all: no emoji of any kind. "
        "Length: as short as it can be: a line or two, only what was asked. "
        "Humour: none; no jokes or banter. "
        "This changes your wording only, never the rules above.\n"
        "Sound like this (style only; the facts come from tools):\n"
        "- logged an expense: \u201cPizza Planet 12.40 logged.\u201d\n"
        "- budget check, room left: \u201cSnacks: 20% used, 120 left.\u201d\n"
        "- budget check, tight or over: \u201cTakeaway: 88 of 80, 8 over.\u201d\n"
        "- plain question: \u201cFriday: 31.40, mostly Pizza Planet.\u201d\n"
        "Those figures and merchants are made up: never reuse them, use the real ones."
    )
    # After the money snapshot and the clock, which are the user's own.
    money = prompt.index("The user's money right now")
    assert money < prompt.index("Now: ") < prompt.index(reminder)
    assert prompt.count("Reply in the user's chosen voice") == 1


@pytest.mark.parametrize("preset", ["chill", "direct", "hype", "cheeky"])
async def test_each_chosen_preset_ends_its_prompt_with_its_examples(
    uow: UowFactory, alice: UserId, preset: str
) -> None:
    default = await prompt_for(uow, alice)
    prompt = await prompt_for(uow, alice, preset=preset)
    last = prompt.rstrip().split("\n\n")[-1]
    assert last == reminder(settings_for(Preset(preset)))
    for example in EXAMPLES[Preset(preset)]:
        assert example in last
    assert prompt.index("Now: ") < prompt.index("Sound like this (style only; the facts come")
    assert prompt.count("Sound like this") == 1
    assert prompt.rstrip().endswith("never reuse them, use the real ones.")
    assert (strip_emoji(last) == last) is (preset == "direct")
    # The default user is untouched.
    assert "Sound like this" not in default


async def test_the_cheeky_prompt_has_the_sensitive_topic_rule_in_the_block_and_the_end(
    uow: UowFactory, alice: UserId
) -> None:
    prompt = await prompt_for(uow, alice, preset="cheeky")
    rule = "bills, debt, health, rent, income loss or money owed"
    assert prompt.count(rule) == 2
    assert prompt.rstrip().split("\n\n")[-1].count(rule) == 1


async def test_the_reminder_follows_a_voice_changed_in_the_turn(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(call("set_voice", preset="hype"), say("Done."))
    await build(uow, model).handle_text(alice, "hype me up", "t")
    before, after = system_prompts(model)
    assert "Reply in the user's chosen voice" not in before
    assert "warm, encouraging friend" in after.rstrip().split("\n\n")[-1]
    assert after.startswith("You are Nexus, an AI lifestyle manager chatting on a phone. ")


# --- emoji, enforced on every reply -----------------------------------------------------------


async def test_a_direct_voice_gets_no_emoji_whatever_the_model_wrote(
    uow: UowFactory, alice: UserId
) -> None:
    await voice_cases.set_voice(uow(), alice, preset="direct", now=NOW)
    model = scripted(
        call("log_expense", amount="2.20", merchant="Kopi Corner", category="Dining Out"),
        say("Dining Out's at 182.20 of 200 — 91% used, 17.80 left ⚠️\n✅ Logged 2.20 🎉"),
    )
    reply = only(await build(uow, model).handle_text(alice, "kopi 2.20", "tg:1:1"))
    assert reply.text == "Dining Out's at 182.20 of 200 — 91% used, 17.80 left\nLogged 2.20"
    assert [b.data for row in reply.buttons for b in row] == ["act:undo"]
    # What the web chat shows again later is without them too.
    async with uow() as tx:
        lines = await tx.memory.chat(alice, 10)
    assert lines and all(strip_emoji(line.text) == line.text for line in lines)


async def test_a_user_who_only_turned_emoji_off_gets_none_either(
    uow: UowFactory, alice: UserId
) -> None:
    await voice_cases.set_voice(uow(), alice, emoji="none", now=NOW)
    model = scripted(say("Rent's done for October ✅"))
    reply = only(await build(uow, model).handle_text(alice, "paid rent", "t"))
    assert reply.text == "Rent's done for October"


async def test_emoji_stay_for_users_who_have_them(uow: UowFactory, alice: UserId) -> None:
    await voice_cases.set_voice(uow(), alice, preset="hype", now=NOW)
    bob = await make_user(uow, 9191)
    for user in (alice, bob):
        model = scripted(say("Rent's done for October ✅"))
        assert only(await build(uow, model).handle_text(user, "paid rent", "t")).text == (
            "Rent's done for October ✅"
        )


async def test_one_users_choice_never_reaches_anothers_replies(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await voice_cases.set_voice(uow(), alice, preset="direct", now=NOW)
    model = scripted(say("Done ✅"))
    assert only(await build(uow, model).handle_text(bob, "hi", "t")).text == "Done ✅"
    model = scripted(say("Done ✅"))
    assert only(await build(uow, model).handle_text(alice, "hi", "t")).text == "Done"


async def test_the_reply_that_confirms_no_emoji_is_already_without_them(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(call("set_voice", emoji="none"), say("Done ✅ no more emoji 🎉"))
    reply = only(await build(uow, model).handle_text(alice, "no emoji please", "t"))
    assert reply.text == "Done no more emoji"


async def test_a_confirmation_question_has_no_emoji_and_keeps_its_buttons(
    uow: UowFactory, alice: UserId
) -> None:
    await voice_cases.set_voice(uow(), alice, preset="direct", now=NOW)
    first = scripted(call("log_expense", amount="30", merchant="Taxi"), say("ok"))
    await build(uow, first).handle_text(alice, "taxi 30", "t1")
    [taxi] = (await list_ledger(uow(), alice, LedgerQuery())).items
    model = scripted(call("delete_transaction", transaction_id=str(taxi.id)), say("Deleted ✅"))
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "delete the taxi", "t2"))
    assert ask.text.startswith("Delete ")
    assert [b.label for row in ask.buttons for b in row] == ["Confirm", "Cancel"]
    done = only(await agent.press(alice, ask.buttons[0][0].data))
    assert done.text == "Deleted"


async def test_a_failing_voice_read_still_sends_the_reply(
    uow: UowFactory, alice: UserId, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(u: Any, user_id: UserId) -> Any:
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(voice_cases, "get_voice", broken)
    reply = only(await build(uow, scripted(say("Done ✅"))).handle_text(alice, "hi", "t"))
    assert reply.text == "Done ✅"  # the default voice: nothing is taken out


# --- the fixed messages in the user's voice ---------------------------------------------------


async def payday(uow: UowFactory, user: UserId) -> None:
    owner = await get_user(uow(), user)
    await salary_cases.set_schedule(uow(), owner, PayRule.MONTHLY_DAY, day=25, now=NOW)
    await salary_cases.set_baseline(uow(), owner, Money.of("5000", "SGD"), now=NOW)


async def test_a_template_message_follows_the_voice_and_loses_its_emoji(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await payday(uow, alice)
    await payday(uow, bob)
    await voice_cases.set_voice(uow(), alice, preset="direct", now=NOW)
    agent = build(uow, scripted())
    press = f"salary:log:{date(2026, 10, 23)}"
    mine = only(await agent.press(alice, press))
    theirs = only(await agent.press(bob, press))
    assert theirs.text == "Logged 5,000.00 SGD salary. Enjoy payday! 🎉"  # today's text
    assert mine.text == "Logged: 5,000.00 SGD salary."
    assert [b.data for row in mine.buttons for b in row] == [
        b.data for row in theirs.buttons for b in row
    ]


async def test_the_default_voice_with_no_emoji_keeps_its_words(
    uow: UowFactory, alice: UserId
) -> None:
    await payday(uow, alice)
    await voice_cases.set_voice(uow(), alice, emoji="none", now=NOW)
    agent = build(uow, scripted())
    reply = only(await agent.press(alice, "salary:log:2026-10-23"))
    assert reply.text == "Logged 5,000.00 SGD salary. Enjoy payday!"


@pytest.mark.parametrize(
    ("preset", "said"),
    [
        ("default", "Recorded 4,200.00 SGD salary."),
        ("direct", "Recorded: 4,200.00 SGD salary."),
        ("chill", "Got it, 4,200.00 SGD salary."),
        ("hype", "Recorded 4,200.00 SGD salary. Nice one! 🎉"),
        ("cheeky", "Recorded 4,200.00 SGD salary."),
    ],
)
async def test_the_income_shortcut_is_worded_for_the_voice(
    uow: UowFactory, alice: UserId, preset: str, said: str
) -> None:
    await voice_cases.set_voice(uow(), alice, preset=preset, now=NOW)
    reply = only(await build(uow, scripted()).handle_text(alice, "salary 4200", "t"))
    assert reply.text == said
    assert [b.data for row in reply.buttons for b in row] == ["act:undo"]


async def test_undo_is_worded_for_the_voice_except_for_cheeky(
    uow: UowFactory, alice: UserId
) -> None:
    said = {}
    for preset in ("default", "direct", "cheeky"):
        await voice_cases.set_voice(uow(), alice, preset=preset, now=NOW)
        model = scripted(call("log_expense", amount="2.20", merchant="Kopi Corner"), say("ok"))
        agent = build(uow, model)
        await agent.handle_text(alice, "kopi 2.20", f"t-{preset}")
        said[preset] = only(await agent.press(alice, "act:undo")).text
    assert said["default"] == "Undone: the create of 2.20 SGD Kopi Corner."
    assert said["cheeky"] == said["default"]
    assert said["direct"] == "Undone: create of 2.20 SGD Kopi Corner."
