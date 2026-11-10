"""Web search in the evals: the canned lookup, the web cases, and ``--live-web``."""

import re
from pathlib import Path
from uuid import uuid4

import pytest

from nexus.domain.ledger import UserId
from nexus.evals import seed
from nexus.evals.__main__ import main
from nexus.evals.cases import CASES, Has
from nexus.evals.live_web import live_settings
from nexus.evals.web import DOMAIN, CannedLookup

USER = UserId(uuid4())


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
        assert wanted.tool == "web_search" and isinstance(wanted.args["question"], Has)
        assert [(cap.tool, cap.n) for cap in case.at_most] == [("web_search", 2)]
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
