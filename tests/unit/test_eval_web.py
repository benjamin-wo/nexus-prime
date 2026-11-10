"""Web search in the evals: the canned lookup, the web cases, and ``--live-web``."""

import re
from pathlib import Path
from uuid import uuid4

import pytest

from nexus.domain.ledger import UserId
from nexus.evals import seed
from nexus.evals.__main__ import main
from nexus.evals.cases import CASES, Case, Has, searches_web
from nexus.evals.checks import World
from nexus.evals.live_web import live_settings
from nexus.evals.runner import TurnLog, grade
from nexus.evals.web import DOMAIN, CannedLookup

USER = UserId(uuid4())
COMPARING = {"web-savings-rates"}
# The price of a product is product_prices's to look up, not a web search's.
PRODUCT_PRICES = {"web-console-price", "web-phone-price"}


async def test_the_canned_lookup_cites_one_made_up_page_and_records_questions() -> None:
    lookup = CannedLookup()
    first = await lookup.ask(USER, "singapore weather today", recent="today")
    await lookup.ask(USER, "usd to sgd rate")
    assert lookup.questions == ["singapore weather today", "usd to sgd rate"]
    assert first.question == "singapore weather today"
    assert "[1]" in first.text and first.read_pages
    [source] = first.sources
    assert source.id == 1
    assert source.url.startswith("https://") and DOMAIN in source.url
    assert source.checked_on == seed.NOW.date()
    assert source.published == seed.NOW


def test_the_web_cases_search_with_a_cap_and_change_nothing() -> None:
    web = [c for c in CASES if c.area == "web"]
    assert len({c.id for c in web}) == len(web) >= 23
    searching = [c for c in web if not c.id.startswith("web-skip-")]
    assert len(searching) >= 20
    for case in searching:
        [wanted] = case.calls
        tool, argument = (
            ("product_prices", "query") if case.id in PRODUCT_PRICES else ("web_search", "question")
        )
        assert wanted.tool == tool and isinstance(wanted.args[argument], Has)
        # Two searches, three for a comparison of rates.
        most = 3 if case.id in COMPARING else 2
        assert [(cap.tool, cap.n) for cap in case.at_most] == [(tool, most)]
        assert case.unchanged and "create_trip" in case.forbid
    skipping = [c for c in web if c.id.startswith("web-skip-")]
    assert len(skipping) == 3
    assert all(c.forbid == ("web_search",) and not c.calls for c in skipping)


def test_web_case_ids_are_unique_across_all_cases() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"web-[a-z0-9-]+", c.id) for c in CASES if c.area == "web")


def _without_tavily(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here to bring a key back


def test_live_web_without_a_tavily_key_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _without_tavily(monkeypatch, tmp_path)
    with pytest.raises(SystemExit, match="TAVILY_API_KEY"):
        live_settings("sk-made-up", "some/model")


async def test_the_eval_command_stops_before_anything_starts_without_a_tavily_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _without_tavily(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-made-up")
    monkeypatch.delenv("EVAL_DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as stopped:
        await main(["--model", "some/model", "--area", "web", "--live-web"])
    assert "TAVILY_API_KEY" in str(stopped.value)
    assert "sk-made-up" not in str(stopped.value)


def test_live_web_uses_the_apps_settings_and_the_eval_model_for_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _without_tavily(monkeypatch, tmp_path)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-made-up")
    monkeypatch.delenv("TRAVEL_RESEARCH_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    settings = live_settings("sk-made-up", "some/model")
    assert settings.travel_research_model == "some/model"
    monkeypatch.setenv("TRAVEL_RESEARCH_MODEL", "other/model")
    assert live_settings("sk-made-up", "some/model").travel_research_model == "other/model"


def test_which_cases_run_on_the_live_clock() -> None:
    searching = {c.id for c in CASES if searches_web(c)}
    assert {"web-gold-price", "web-skip-capital", "web-search-protest-now"} <= searching
    assert not {c.id for c in CASES if c.area == "log"} & searching


async def _grade(case: Case, log: TurnLog) -> list[str]:
    world = World(uow=lambda: None, user=None, seeded=frozenset())  # type: ignore[arg-type,return-value]
    return await grade(case, [log], world, changed=False)


def _cited(case_id: str) -> Case:
    return next(c for c in CASES if c.id == case_id)


async def test_a_web_answer_may_name_its_source_in_any_usual_way() -> None:
    case = _cited("web-gold-price")
    assert case.source_buttons
    call = [("web_search", {"question": "gold price today"})]
    link = ["src:https://news.example.com/x"]
    for reply in (
        "Gold is S$4,100 an ounce, per Example Daily.",
        "According to the Straits Times it is up.",
        "The source says it is up.",
        "See https://news.example.com",
        "Per HardwareZone, it is up.",
    ):
        assert await _grade(case, TurnLog("q", [reply], link, call)) == []
    plain = TurnLog("q", ["Gold is up a bit today."], link, call)
    assert await _grade(case, plain) == [
        "reply lacks ('source', 'per ', 'according to', 'http', 'example')"
    ]


async def test_a_cited_web_answer_must_carry_a_source_link_button() -> None:
    case = _cited("web-gold-price")
    call = [("web_search", {"question": "gold price today"})]
    said = "Gold is up, per Example Daily."
    assert await _grade(case, TurnLog("q", [said], ["act:undo"], call)) == [
        "reply has no source link buttons"
    ]
    assert await _grade(case, TurnLog("q", [said], ["src:https://news.example.com/x"], call)) == []
    # A case that doesn't ask for it doesn't mind.
    assert not _cited("web-weather-tomorrow").source_buttons


def test_turn_logs_know_the_pages_a_reply_links_to() -> None:
    log = TurnLog("q", ["a"], ["act:undo", "src:https://a.example.com/1", "url:https://x.com"])
    assert log.source_links == ["https://a.example.com/1"]
    assert TurnLog("q").source_links == []
