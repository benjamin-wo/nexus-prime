"""What a model call costs: reading the cost out of a reply, naming who it was for, and the
figures on the owner's cost page. Every name, model and figure here is made up."""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from nexus.application import cost_report, costs
from nexus.application.acting import acting_as
from nexus.application.cost_report import Row
from nexus.domain.ledger import UserId
from nexus.infra.cost_store import keep_from
from nexus.infra.llm.factory import (
    OPENROUTER_URL,
    build_chat_models,
    build_email_reader,
    build_image_look_models,
    build_memory_model,
    build_research_models,
    build_research_reviewer,
    build_screener,
    build_screenshot_reader,
    build_travel_sorter,
    build_web_writer,
)
from nexus.infra.llm.usage import COST_CALLBACK, usage_of
from nexus.settings import Settings

D = Decimal
ANN = UUID("11111111-1111-1111-1111-111111111111")
BEN = UUID("22222222-2222-2222-2222-222222222222")


# --- reading a reply ------------------------------------------------------------------------


def result(
    *,
    output: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
) -> LLMResult:
    message = AIMessage(content="hi", response_metadata=metadata or {})
    if usage is not None:
        message.usage_metadata = usage  # type: ignore[assignment]
    return LLMResult(generations=[[ChatGeneration(message=message)]], llm_output=output)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.00123, D("0.00123")),
        ("0.0042", D("0.0042")),
        (3, D(3)),
        (D("1.5"), D("1.5")),
        (0, D(0)),
        (-1, D(0)),
        (float("nan"), D(0)),
        (float("inf"), D(0)),
        ("free", D(0)),
        ("", D(0)),
        (None, D(0)),
        (True, D(0)),
        ({"usd": 1}, D(0)),
    ],
)
def test_a_cost_is_read_from_whatever_the_provider_sent(value: object, expected: Decimal) -> None:
    assert costs.to_cost(value) == expected


def test_openrouters_usage_in_the_models_own_output() -> None:
    reply = result(
        output={
            "token_usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 300,
                "total_tokens": 1500,
                "cost": 0.000456,
                "cost_details": {"upstream_inference_cost": 0.0004},
            },
            "model_name": "made-up/model",
        }
    )
    used = usage_of(reply)
    assert (used.input_tokens, used.output_tokens, used.cost) == (1200, 300, D("0.000456"))


def test_usage_in_the_messages_metadata() -> None:
    reply = result(metadata={"token_usage": {"prompt_tokens": 80, "completion_tokens": 20,
                                             "total_cost": "0.0009"}})  # fmt: skip
    used = usage_of(reply)
    assert (used.input_tokens, used.output_tokens, used.cost) == (80, 20, D("0.0009"))
    again = result(metadata={"usage": {"input_tokens": 7, "output_tokens": 3, "cost": 0.5}})
    used = usage_of(again)
    assert (used.input_tokens, used.output_tokens, used.cost) == (7, 3, D("0.5"))


def test_a_provider_without_a_cost_counts_tokens_at_zero() -> None:
    # Gemini and plain OpenAI: tokens, no dollars.
    reply = result(usage={"input_tokens": 50, "output_tokens": 10, "total_tokens": 60})
    used = usage_of(reply)
    assert (used.input_tokens, used.output_tokens, used.cost) == (50, 10, D(0))
    deepseek = result(output={"token_usage": {"prompt_tokens": 9, "completion_tokens": 4}})
    used = usage_of(deepseek)
    assert (used.input_tokens, used.output_tokens, used.cost) == (9, 4, D(0))


def test_a_reply_with_no_usage_is_zero_and_garbage_is_ignored() -> None:
    assert usage_of(result()) == usage_of(LLMResult(generations=[], llm_output=None))
    assert usage_of(result()).cost == D(0)
    junk = result(
        output={"token_usage": {"prompt_tokens": "lots", "completion_tokens": -4, "cost": "?"}},
        metadata={"token_usage": "not a dict"},
    )
    used = usage_of(junk)
    assert (used.input_tokens, used.output_tokens, used.cost) == (0, 0, D(0))


# --- who it was for ------------------------------------------------------------------------


@pytest.fixture
def charges() -> Iterator[list[costs.Charge]]:
    found: list[costs.Charge] = []
    costs.set_sink(found.append)
    try:
        yield found
    finally:
        costs.set_sink(None)


def test_nothing_is_recorded_without_a_sink() -> None:
    costs.record("made-up/model", cost=1)  # no sink: nothing happens, nothing raises


def test_a_call_counts_under_the_feature_and_user_in_force(charges: list[costs.Charge]) -> None:
    costs.record("made-up/model", input_tokens=10, output_tokens=2, cost="0.01")
    with costs.scope("chat", user=ANN):
        costs.record("made-up/model", cost=0.5)
        with costs.scope("voice"):  # the user stays
            costs.record("made-up/model")
        with costs.scope("memory.update", user=None):  # work for no one
            costs.record("made-up/model")
    costs.record("made-up/model")
    assert [(c.feature, c.user_id) for c in charges] == [
        ("unknown", None),
        ("chat", ANN),
        ("voice", ANN),
        ("memory.update", None),
        ("unknown", None),
    ]
    first = charges[0]
    assert (first.calls, first.input_tokens, first.output_tokens, first.cost) == (
        1, 10, 2, D("0.01"),
    )  # fmt: skip


def test_a_turn_started_by_a_voice_note_stays_voice(charges: list[costs.Charge]) -> None:
    with costs.scope("voice", user=ANN):
        with costs.scope("chat", user=ANN, keep=True):
            costs.record("made-up/model")
    with costs.scope("chat", user=ANN, keep=True):  # nothing named it: it is chat
        costs.record("made-up/model")
    assert [c.feature for c in charges] == ["voice", "chat"]


def test_the_user_a_request_is_for_is_the_fallback(charges: list[costs.Charge]) -> None:
    with acting_as(UserId(BEN)):
        costs.record("made-up/model")
        with costs.scope("pdf", user=ANN):  # named outright: wins
            costs.record("made-up/model")
    assert [c.user_id for c in charges] == [BEN, ANN]


def test_a_user_that_is_not_one_counts_as_no_one(charges: list[costs.Charge]) -> None:
    with costs.scope("email.sweep", user="not-a-uuid"):
        costs.record("made-up/model")
    with costs.scope("email.sweep", user=str(ANN)):
        costs.record("made-up/model")
    assert [c.user_id for c in charges] == [None, ANN]


def test_the_scope_ends_with_the_block(charges: list[costs.Charge]) -> None:
    with costs.scope("chat", user=ANN):
        pass
    costs.record("made-up/model")
    assert (charges[0].feature, charges[0].user_id) == ("unknown", None)


def test_recording_never_raises(charges: list[costs.Charge]) -> None:
    def broken(_: costs.Charge) -> None:
        raise RuntimeError("the buffer is gone")

    costs.set_sink(broken)
    costs.record("made-up/model", cost=1)  # swallowed


def test_long_names_are_cut(charges: list[costs.Charge]) -> None:
    with costs.scope("f" * 500):
        costs.record("m" * 500)
    assert len(charges[0].feature) == costs.MAX_FEATURE and len(charges[0].model) == costs.MAX_MODEL


# --- every model the factory builds counts its calls -----------------------------------------


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, database_url="postgresql://u:p@h/db", **values)


def test_every_model_is_built_to_count_and_openrouter_is_asked_for_the_cost() -> None:
    config = settings(
        llm_provider="openrouter",
        openrouter_api_key="or-key",
        openrouter_model="made-up/main",
        openrouter_fallback_models="made-up/backup",
        openrouter_vision_model="made-up/eyes",
        image_look_model="made-up/glance",
        memory_model="made-up/memory",
        email_classifier_model="made-up/screen",
        research_review_model="made-up/review",
    )
    chat = build_chat_models(config)
    analyst, lead = build_research_models(config, chat.primary)
    first, second = build_image_look_models(config, chat.vision or chat.primary)
    built = [
        chat.primary,
        *chat.fallbacks,
        chat.vision,
        build_screener(config, chat.primary),
        build_email_reader(config, chat.primary),
        build_memory_model(config, chat.primary),
        build_screenshot_reader(config, chat.vision or chat.primary),
        analyst,
        lead,
        build_research_reviewer(config),
        first,
        second,
        build_travel_sorter(config, "made-up/sorter"),
        build_web_writer(config, "made-up/writer"),
    ]
    models = [m for m in built if m is not None]
    assert len(models) >= 12
    for model in models:
        assert isinstance(model, ChatOpenAI)
        assert COST_CALLBACK in (model.callbacks or [])
        assert model.openai_api_base == OPENROUTER_URL
        assert model.extra_body is not None and model.extra_body["usage"] == {"include": True}


def test_other_providers_count_tokens_without_asking_openrouter() -> None:
    plain = build_chat_models(
        settings(llm_provider="openai", openai_api_key="oa-key", openai_model="made-up/plain")
    ).primary
    assert isinstance(plain, ChatOpenAI) and COST_CALLBACK in (plain.callbacks or [])
    assert not (plain.extra_body or {}).get("usage")
    gemini = build_chat_models(settings(llm_provider="gemini", gemini_api_key="g-key")).primary
    assert COST_CALLBACK in (gemini.callbacks or [])


# --- a whole call, through the real client -----------------------------------------------------


def reply(
    content: str = "hi", *, cost: float | None = 0.00123, tool: dict[str, Any] | None = None
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool is not None:
        message["tool_calls"] = [
            {"id": "c1", "type": "function",
             "function": {"name": tool["name"], "arguments": json.dumps(tool["args"])}}
        ]  # fmt: skip
    usage: dict[str, Any] = {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125}
    if cost is not None:
        usage["cost"] = cost
    return {
        "id": "gen-1",
        "object": "chat.completion",
        "created": 1,
        "model": "made-up/model",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": usage,
    }


def wire(model: Any, handler: Callable[[httpx.Request], httpx.Response]) -> list[dict[str, Any]]:
    """Answer ``model``'s requests with ``handler`` instead of the network; returns the
    request bodies it was sent."""
    sent: list[dict[str, Any]] = []

    def serve(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return handler(request)

    client = openai.AsyncOpenAI(
        api_key="k",
        base_url=OPENROUTER_URL,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(serve)),
        max_retries=0,
    )
    model.root_async_client = client
    model.async_client = client.chat.completions
    return sent


def ok(body: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _: httpx.Response(200, json=body)


def main_model() -> ChatOpenAI:
    config = settings(
        llm_provider="openrouter", openrouter_api_key="or-key", openrouter_model="made-up/main"
    )
    model = build_chat_models(config).primary
    assert isinstance(model, ChatOpenAI)
    return model


async def test_a_call_asks_for_usage_and_is_counted(charges: list[costs.Charge]) -> None:
    model = main_model()
    sent = wire(model, ok(reply("Logged it.")))
    with costs.scope("chat", user=ANN):
        answer = await model.ainvoke("a made-up question")
    assert answer.content == "Logged it."
    assert sent[0]["usage"] == {"include": True}
    [charge] = charges
    assert (charge.feature, charge.user_id, charge.model) == ("chat", ANN, "made-up/main")
    assert (charge.calls, charge.input_tokens, charge.output_tokens) == (1, 100, 25)
    assert charge.cost == D("0.00123")
    assert charge.day == datetime.now(UTC).date()
    # Never the words.
    assert "question" not in repr(charge) and "Logged" not in repr(charge)


async def test_a_reply_without_a_cost_still_counts_the_call(charges: list[costs.Charge]) -> None:
    model = main_model()
    wire(model, ok(reply(cost=None)))
    await model.ainvoke("hello")
    [charge] = charges
    assert (charge.calls, charge.input_tokens, charge.cost) == (1, 100, D(0))
    assert charge.feature == "unknown" and charge.user_id is None


class Answer(BaseModel):
    text: str


async def test_structured_output_is_counted_too(charges: list[costs.Charge]) -> None:
    model = main_model()
    body = reply(tool={"name": "Answer", "args": {"text": "yes"}}, cost=0.002)
    wire(model, ok(body))
    structured = model.with_structured_output(Answer, method="function_calling")
    with costs.scope("travel.photos"):
        found = await structured.ainvoke("is it a sight?")
    assert found == Answer(text="yes")
    [charge] = charges
    assert charge.feature == "travel.photos" and charge.cost == D("0.002")


async def test_only_the_model_that_answered_is_counted_in_a_fallback(
    charges: list[costs.Charge],
) -> None:
    config = settings(
        llm_provider="openrouter",
        openrouter_api_key="or-key",
        openrouter_model="made-up/main",
        openrouter_fallback_models="made-up/backup",
    )
    chat = build_chat_models(config)
    main, backup = chat.primary, chat.fallbacks[0]
    assert isinstance(main, ChatOpenAI) and isinstance(backup, ChatOpenAI)
    wire(main, lambda _: httpx.Response(500, json={"error": {"message": "down"}}))
    wire(backup, ok(reply("From the backup.", cost=0.004)))
    with costs.scope("chat", user=BEN):
        answer = await main.with_fallbacks([backup]).ainvoke("hello")
    assert answer.content == "From the backup."
    [charge] = charges  # the failed call cost nothing and is not counted
    assert (charge.model, charge.cost, charge.user_id) == ("made-up/backup", D("0.004"), BEN)


async def test_a_failed_call_leaves_nothing_behind(charges: list[costs.Charge]) -> None:
    model = main_model()
    wire(model, lambda _: httpx.Response(500, json={"error": {"message": "down"}}))
    with pytest.raises(openai.APIError):
        await model.ainvoke("hello")
    assert charges == []
    assert COST_CALLBACK._models == {}  # no call is left waiting


# --- the figures ---------------------------------------------------------------------------


def row(
    day: str, cost: str, *, user: UUID | None = ANN, feature: str = "chat",
    model: str = "made-up/main", calls: int = 1, tokens: tuple[int, int] = (100, 20),
) -> Row:  # fmt: skip
    return Row(date.fromisoformat(day), user, feature, model, calls, tokens[0], tokens[1], D(cost))


TODAY = date(2026, 10, 28)  # 28 of 31 days
NAMES: dict[UUID, str | None] = {ANN: "Ann", BEN: None}


def test_the_month_to_date_and_its_projection() -> None:
    rows = [
        row("2026-09-30", "50"),  # last month: not this month's
        row("2026-10-01", "4"),
        row("2026-10-20", "6"),
        row("2026-10-28", "2.5"),
        row("2026-10-29", "99"),  # tomorrow (clock skew): not counted
    ]
    month = cost_report.month_figures(rows, TODAY)
    assert month == {
        "start": "2026-10-01",
        "spent": "12.5000",
        "projected": "13.84",  # 12.5 / 28 * 31 = 13.839...
        "days_elapsed": 28,
        "days_in_month": 31,
    }


def test_the_first_of_the_month_projects_from_one_day() -> None:
    month = cost_report.month_figures([row("2026-11-01", "1")], date(2026, 11, 1))
    assert (month["days_elapsed"], month["days_in_month"]) == (1, 30)
    assert month["spent"] == "1.0000" and month["projected"] == "30.00"


def test_an_empty_month_is_zero() -> None:
    built = cost_report.build([], {}, TODAY, 3)
    assert built["month"]["spent"] == "0.0000" and built["month"]["projected"] == "0.00"
    assert built["by_feature"] == built["by_user"] == built["by_model"] == []
    assert built["per_active_user_month"] == "0.00"
    assert [d["cost"] for d in built["days"]] == ["0.0000"] * 3


def test_days_are_the_last_n_oldest_first_and_zero_filled() -> None:
    rows = [
        row("2026-10-24", "1.5", calls=3),
        row("2026-10-24", "0.25", calls=2, feature="memory.update"),
        row("2026-10-27", "2"),
        row("2026-10-22", "9"),  # before the window
    ]
    built = cost_report.build(rows, NAMES, TODAY, 5)
    assert built["currency"] == "USD"
    assert built["days"] == [
        {"day": "2026-10-24", "cost": "1.7500", "calls": 5},
        {"day": "2026-10-25", "cost": "0.0000", "calls": 0},
        {"day": "2026-10-26", "cost": "0.0000", "calls": 0},
        {"day": "2026-10-27", "cost": "2.0000", "calls": 1},
        {"day": "2026-10-28", "cost": "0.0000", "calls": 0},
    ]
    # The month is not the window: the 22nd is in it though it is not among the 5 days.
    assert built["month"]["spent"] == "12.7500"


def test_features_users_and_models_are_ranked_by_cost_with_shares() -> None:
    rows = [
        row("2026-10-27", "6", feature="chat", user=ANN, model="made-up/main", calls=10),
        row("2026-10-27", "1", feature="chat", user=BEN, model="made-up/main", calls=2),
        row("2026-10-28", "2", feature="photo", user=BEN, model="made-up/eyes", calls=4),
        row("2026-10-28", "1", feature="memory.update", user=None, model="made-up/main", calls=7),
    ]
    built = cost_report.build(rows, NAMES, TODAY, 7)
    assert built["by_feature"] == [
        {"feature": "chat", "cost": "7.0000", "calls": 12, "share": 0.7},
        {"feature": "photo", "cost": "2.0000", "calls": 4, "share": 0.2},
        {"feature": "memory.update", "cost": "1.0000", "calls": 7, "share": 0.1},
    ]
    assert built["by_user"] == [
        {"user_id": str(ANN), "name": "Ann", "cost": "6.0000", "calls": 10},
        {"user_id": str(BEN), "name": "User 22222222", "cost": "3.0000", "calls": 6},
        {"user_id": None, "name": "System", "cost": "1.0000", "calls": 7},
    ]
    assert built["by_model"] == [
        {"model": "made-up/main", "cost": "8.0000", "calls": 19, "input_tokens": 300,
         "output_tokens": 60},
        {"model": "made-up/eyes", "cost": "2.0000", "calls": 4, "input_tokens": 100,
         "output_tokens": 20},
    ]  # fmt: skip


def test_shares_are_of_the_window_and_zero_when_nothing_was_spent() -> None:
    thirds = [row("2026-10-28", "1", feature=f) for f in ("a", "b", "c")]
    shares = [f["share"] for f in cost_report.build(thirds, NAMES, TODAY, 1)["by_feature"]]
    assert shares == [0.3333, 0.3333, 0.3333]
    free = [row("2026-10-28", "0", feature="chat", calls=4)]
    built = cost_report.build(free, NAMES, TODAY, 1)
    assert built["by_feature"] == [{"feature": "chat", "cost": "0.0000", "calls": 4, "share": 0.0}]


def test_equal_costs_keep_a_steady_order() -> None:
    rows = [row("2026-10-28", "1", feature=f) for f in ("b", "a", "c")]
    names = [f["feature"] for f in cost_report.build(rows, NAMES, TODAY, 1)["by_feature"]]
    assert names == ["a", "b", "c"]


def test_cost_per_active_user_is_projected_and_leaves_out_the_system() -> None:
    rows = [
        row("2026-10-05", "9", user=ANN),
        row("2026-10-06", "3", user=BEN),
        row("2026-10-07", "100", user=None),  # no one in particular
        row("2026-09-07", "100", user=BEN),  # last month
    ]
    # 12 over 2 users so far = 6 each in 28 days -> 6 / 28 * 31
    assert cost_report.per_active_user_month(rows, TODAY) == "6.64"
    assert cost_report.per_active_user_month([row("2026-10-07", "5", user=None)], TODAY) == "0.00"


def test_money_rounds_half_up_to_the_cent_and_the_fraction() -> None:
    assert cost_report.amount(D("0.00005")) == "0.0001"
    assert cost_report.amount(D("0.000049")) == "0.0000"
    assert cost_report.rounded(D("18.205")) == "18.21"


def test_user_labels() -> None:
    assert cost_report.user_label(ANN, "  Ann   Lee ") == "Ann Lee"
    assert cost_report.user_label(ANN, None) == "User 11111111"
    assert cost_report.user_label(uuid4(), "   ").startswith("User ")


def test_the_markdown_has_every_part_and_cannot_break_a_table() -> None:
    names: dict[UUID, str | None] = {ANN: "Ann | Lee"}
    built = cost_report.build([row("2026-10-28", "2", calls=2)], names, TODAY, 2)
    text = cost_report.markdown(built)
    assert text.startswith("# Nexus model costs")
    for part in ("## Last 2 days", "## By feature", "## By user", "## By model"):
        assert part in text
    assert "| 2026-10-28 | 2.0000 | 2 |" in text
    assert "| chat | 2.0000 | 2 | 100.0% |" in text
    assert "| Ann / Lee | 2.0000 | 2 |" in text
    assert "projected **2.21**" in text  # 2 / 28 * 31


def test_costs_are_kept_for_13_months() -> None:
    assert keep_from(date(2026, 10, 28)) == date(2025, 10, 1)
    assert keep_from(date(2026, 1, 5)) == date(2025, 1, 1)
    assert keep_from(date(2026, 12, 31)) == date(2025, 12, 1)
