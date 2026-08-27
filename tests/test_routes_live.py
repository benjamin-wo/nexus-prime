import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from capabilities.routes import lta
from capabilities.routes.journey import format_journey, plan_transit_journey
from capabilities.routes.tools import (
    _bus_query_parts,
    _selection_intent,
    handle_bus_query,
    is_bare_place_fragment,
    is_bus_arrival_query,
    is_bus_disambiguation_answer,
    plan_route,
)
from core.config import settings


def test_bus_query_parts_extracts_stop_and_service():
    parts = _bus_query_parts("when is the next bus 27 from Tampines West CC")
    assert parts["service"] == "27"
    assert parts["stop_name"] == "tampines west cc"
    parts2 = _bus_query_parts("next bus at 76161")
    assert parts2["stop_code"] == "76161"
    parts3 = _bus_query_parts("when's my next bus tampines west cc")
    assert parts3["stop_name"] == "tampines west cc"
    assert _bus_query_parts("when's my next bus?")["stop_name"] is None
    assert _selection_intent("the first one") == 0
    assert _selection_intent("2") == 1
    assert _selection_intent("nope") is None


def test_bus_arrival_vs_directions_classification():
    assert is_bus_arrival_query("What bus should I take from Tembusu grand to Suntec") is False
    assert is_bus_arrival_query("which bus goes to suntec") is False
    assert is_bus_arrival_query("when's my next bus from Tampines West CC") is True
    assert is_bus_arrival_query("next bus at 76161") is True
    assert is_bus_arrival_query("route from A to B") is False
    assert is_bare_place_fragment("tembusu grand") is True
    assert is_bare_place_fragment("suntec city") is True
    assert is_bare_place_fragment("to suntec") is False
    assert is_bare_place_fragment("what bus should i take") is False
    # Regression (#15): a conversational follow-up rejecting/alternating the
    # current route ("no I want other buses") is not a place name, but used to
    # slip past the exclusion list (no word-boundary "bus" match on "buses",
    # and none of "no"/"want"/"other" were excluded) and get treated as one.
    assert is_bare_place_fragment("no i want other buses") is False
    assert is_bare_place_fragment("other one") is False


def test_disambiguation_answer_matches_pending_stop():
    pending = [
        {"code": "03011", "description": "Fullerton Sq", "road_name": "Fullerton Rd"},
        {"code": "01139", "description": "Bugis Stn/Parkview Sq", "road_name": "Nth Bridge Rd"},
        {"code": "04321", "description": "UE Sq", "road_name": "Clemenceau Ave"},
    ]
    assert is_bus_disambiguation_answer("the first one", pending) is True
    assert is_bus_disambiguation_answer("2", pending) is True
    assert is_bus_disambiguation_answer("03011", pending) is True
    assert is_bus_disambiguation_answer("Fullerton sq", pending) is True
    assert is_bus_disambiguation_answer("fullerton", pending) is True
    assert is_bus_disambiguation_answer("bugis stn/parkview", pending) is True
    assert is_bus_disambiguation_answer("This is a problem", pending) is False
    assert is_bus_disambiguation_answer("Stop", pending) is False
    assert is_bus_disambiguation_answer("what bus should I take", pending) is False
    assert is_bus_disambiguation_answer("Fullerton sq", None) is False


def test_lta_format_arrivals_shows_bus_numbers():
    text = lta.format_arrivals(
        [
            {"service": "27", "arrivals_min": [4, 12]},
            {"service": "969", "arrivals_min": [0]},
        ]
    )
    assert "Bus 27: next 4 min, then 12 min" in text
    assert "Bus 969: next due" in text


def test_fuzzy_search_stops_works_offline():
    stops = [
        {"code": "76161", "description": "Tampines West CC", "road_name": "Tampines Ave 1", "lat": 1.0, "lng": 2.0},
        {"code": "76061", "description": "Tampines East CC", "road_name": "Tampines Ave 4", "lat": 1.0, "lng": 2.0},
        {"code": "99999", "description": "Changi Airport PTB2", "road_name": "Airport Blvd", "lat": 1.0, "lng": 2.0},
    ]
    result = lta.fuzzy_search_stops(stops, "tampines west cc")
    assert result[0]["code"] == "76161"
    assert len(result) == 2
    assert lta.fuzzy_search_stops(stops, "changi")[0]["code"] == "99999"
    assert lta.fuzzy_search_stops(stops, "zzzz") == []
    strict = lta.fuzzy_search_stops(stops, "tampines west cc", min_fraction=0.99)
    assert [s["code"] for s in strict] == ["76161"]
    assert lta.fuzzy_search_stops(stops, "tampines west cc", min_fraction=1.01) == []


@pytest.mark.asyncio
async def test_search_bus_stops_finds_real_match_not_irrelevant_catalog_page(monkeypatch):
    """Regression (#57): a query like "fullerton sq hotel" got back unrelated
    Victoria St stops (Hotel Grand Pacific, St. Joseph's Ch, Bras Basah Cplx)
    in production because search_bus_stops() trusted a "live SearchText" call
    against LTA's BusStops endpoint first -- but per LTA's own API docs that
    endpoint has no free-text search parameter, only $skip/$top pagination,
    so a real LTA server silently ignores SearchText and returns whatever its
    first unfiltered page happens to be, every time, regardless of query.
    Since that page is non-empty it was trusted directly, so the correct
    local fuzzy match was never even attempted. search_bus_stops() must go
    straight to the local catalog's fuzzy match, which correctly finds the
    real "Fullerton Sq" stop over the Victoria St red herrings.

    Mocks _lta_get itself (not search_bus_stops' internals) to faithfully
    reproduce that real-server behavior: any call carrying "SearchText"
    returns the same fixed, irrelevant page no matter what text was sent;
    only the paginated $skip/$top bulk-catalog call returns the real match.
    """
    monkeypatch.setattr(settings, "lta_account_key", "test-lta-key")

    victoria_st_page = {
        "value": [
            {"BusStopCode": "01012", "Description": "Hotel Grand Pacific", "RoadName": "Victoria St"},
            {"BusStopCode": "01013", "Description": "St. Joseph's Ch", "RoadName": "Victoria St"},
            {"BusStopCode": "01019", "Description": "Bras Basah Cplx", "RoadName": "Victoria St"},
        ]
    }
    full_catalog_page = {
        "value": victoria_st_page["value"] + [
            {"BusStopCode": "04121", "Description": "Fullerton Sq", "RoadName": "Fullerton Rd"},
        ]
    }

    async def fake_lta_get(endpoint, params):
        assert endpoint == "BusStops"
        if "SearchText" in params:
            # Real LTA behavior: SearchText is not a real filter -- always
            # the same page, regardless of what text was sent.
            return victoria_st_page
        if params.get("$skip", 0) > 0:
            return {"value": []}
        return full_catalog_page

    monkeypatch.setattr(lta, "_lta_get", fake_lta_get)

    results = await lta.search_bus_stops("fullerton sq hotel")
    assert results
    assert results[0]["code"] == "04121"
    assert results[0]["description"] == "Fullerton Sq"


@pytest.mark.asyncio
async def test_no_live_feed_is_honest_when_key_missing():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings, "lta_account_key", None)
    result = await handle_bus_query("when's my next bus?")
    assert result["kind"] == "no_live_feed"
    assert "won't guess a bus number" in result["message"]
    assert "27" not in result["message"]
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_bus_arrivals_return_actual_service_numbers(monkeypatch):
    monkeypatch.setattr(settings, "lta_account_key", "test-lta-key")
    monkeypatch.setattr(
        lta,
        "get_bus_arrivals",
        AsyncMock(
            return_value=[
                {"service": "27", "arrivals_min": [4, 12]},
                {"service": "969", "arrivals_min": [0]},
            ]
        ),
    )
    result = await handle_bus_query("next bus at 76161")
    assert result["kind"] == "arrivals"
    assert "Bus 27: next 4 min" in result["message"]
    assert "Bus 969: next due" in result["message"]


@pytest.mark.asyncio
async def test_ambiguous_stop_asks_which_one(monkeypatch):
    monkeypatch.setattr(settings, "lta_account_key", "test-lta-key")
    monkeypatch.setattr(
        lta,
        "search_bus_stops",
        AsyncMock(
            return_value=[
                {"code": "76161", "description": "Tampines West CC", "road_name": "Tampines Ave 1"},
                {"code": "76061", "description": "Tampines East CC", "road_name": "Tampines Ave 4"},
            ]
        ),
    )
    result = await handle_bus_query("next bus from Tampines")
    assert result["kind"] == "stop_ambiguous"
    assert "Which stop did you mean?" in result["message"]
    assert "76161" in result["message"]
    assert len(result["pending_stops"]) == 2


@pytest.mark.asyncio
async def test_selection_followup_resolves_pending_stop(monkeypatch):
    monkeypatch.setattr(settings, "lta_account_key", "test-lta-key")
    monkeypatch.setattr(
        lta,
        "get_bus_arrivals",
        AsyncMock(return_value=[{"service": "27", "arrivals_min": [4, 12]}]),
    )
    pending = [
        {"code": "76161", "description": "Tampines West CC", "road_name": "Tampines Ave 1"},
        {"code": "76061", "description": "Tampines East CC", "road_name": "Tampines Ave 4"},
    ]
    result = await handle_bus_query("the first one", pending_stops=pending)
    assert result["kind"] == "arrivals"
    assert "Tampines West CC (76161" in result["message"]
    assert "Bus 27" in result["message"]


# orchestrator/router.py's RoutePlugin (deleted) used a dedicated
# `pending_bus_stops` AssistantState field to keep a place-name follow-up
# ("Fullerton sq") answering a bus-stop disambiguation instead of being
# hijacked into fresh journey planning. That field is gone: get_bus_timings'
# own disambiguation reply already lists the candidate stops/codes in its
# ToolMessage content, so the agent resolves a follow-up itself by reading
# its own prior turn -- no dedicated state plumbing needed. See
# test_get_bus_timings_handles_ambiguous above for the tool-level coverage
# of that disambiguation reply shape.


@pytest.mark.asyncio
async def test_get_bus_arrivals_parses_v3_services(monkeypatch):
    from datetime import datetime, timedelta, timezone

    future = datetime.now(timezone.utc) + timedelta(minutes=4)
    payload = {
        "BusStopCode": "01012",
        "Services": [
            {
                "ServiceNo": "12",
                "NextBus": {"EstimatedArrival": future.isoformat()},
                "NextBus2": {"EstimatedArrival": None},
                "NextBus3": {"EstimatedArrival": None},
            }
        ],
    }
    mock_get = AsyncMock(return_value=payload)
    monkeypatch.setattr(lta, "_lta_get", mock_get)
    arrivals = await lta.get_bus_arrivals("01012", "12")
    assert arrivals[0]["service"] == "12"
    minutes = arrivals[0]["arrivals_min"][0]
    assert minutes is not None and 0 <= minutes <= 5
    endpoint = mock_get.await_args.args[0]
    assert endpoint == "v3/BusArrival"


def _journey_directions_payload(departure_epoch=None):
    transit = {
        "line": {"short_name": "27", "name": "Tampines Int"},
        "departure_stop": {"name": "Tampines West CC"},
        "arrival_stop": {"name": "Changi Airport"},
        "departure_time": {"value": departure_epoch} if departure_epoch else {},
    }
    return {
        "status": "OK",
        "routes": [
            {
                "legs": [
                    {
                        "duration": {"text": "35 mins", "value": 2100},
                        "distance": {"text": "12 km", "value": 12000},
                        "steps": [
                            {
                                "html_instructions": "Walk to Tampines West CC",
                                "duration": {"text": "4 mins"},
                            },
                            {
                                "html_instructions": "",
                                "duration": {"text": "25 mins"},
                                "transit_details": transit,
                            },
                        ],
                    }
                ]
            }
        ],
    }


@pytest.mark.asyncio
async def test_journey_composes_maps_and_lta(monkeypatch):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(settings, "google_maps_api_key", "test-maps-key")
    monkeypatch.setattr(settings, "lta_account_key", "test-lta-key")
    departure = datetime(2026, 8, 8, 14, 32, tzinfo=ZoneInfo("Asia/Singapore")).timestamp()
    payload = _journey_directions_payload(departure)

    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client

    monkeypatch.setattr(
        lta,
        "ensure_stop_catalog",
        AsyncMock(
            return_value=[
                {"code": "76161", "description": "Tampines West CC", "road_name": "Tampines Ave 1"},
            ]
        ),
    )
    monkeypatch.setattr(
        lta,
        "get_bus_arrivals",
        AsyncMock(return_value=[{"service": "27", "arrivals_min": [4, 12]}]),
    )

    with patch("capabilities.routes.journey.httpx.AsyncClient", mock_client_cls):
        journey = await plan_transit_journey("Tampines MRT", "Changi Airport")

    assert journey.get("error") is None
    transit_step = journey["steps"][1]
    assert transit_step["kind"] == "transit"
    assert transit_step["line"] == "27"
    assert transit_step["live_minutes"] == 4
    assert journey["steps"][0]["kind"] == "walk"
    text = format_journey(journey)
    assert "27: Tampines West CC → Changi Airport (25 mins) · next in ~4 min" in text
    assert "Open in Maps" in text


@pytest.mark.asyncio
async def test_journey_falls_back_to_schedule_without_lta(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(settings, "google_maps_api_key", "test-maps-key")
    monkeypatch.setattr(settings, "lta_account_key", None)
    departure = datetime(2026, 8, 8, 14, 32, tzinfo=ZoneInfo("Asia/Singapore")).timestamp()
    mock_resp = MagicMock()
    mock_resp.json.return_value = _journey_directions_payload(departure)
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    with patch("capabilities.routes.journey.httpx.AsyncClient", mock_client_cls):
        journey = await plan_transit_journey("Tampines MRT", "Changi Airport")
    assert journey["steps"][1]["live_minutes"] is None
    assert journey["steps"][1]["scheduled_time"] == "14:32"
    assert "departs 14:32" in format_journey(journey)


def _two_route_directions_payload():
    """Two distinct alternative routes -- regression coverage for PR #65
    (Directions was called with alternatives="false", so a user asking for
    "another route" always got back the exact same journey). Formerly
    exercised via RoutePlugin's own tests (deleted with orchestrator/router.py
    -- route_index/alternatives now live entirely in plan_transit_journey and
    the agent-callable transit_journey tool, tested here and below)."""
    payload = _journey_directions_payload()
    second = _journey_directions_payload()
    second["routes"][0]["legs"][0]["duration"] = {"text": "50 mins", "value": 3000}
    second["routes"][0]["legs"][0]["steps"][1]["transit_details"]["line"]["short_name"] = "12"
    payload["routes"].append(second["routes"][0])
    return payload


@pytest.mark.asyncio
async def test_plan_transit_journey_cycles_to_next_alternative(monkeypatch):
    monkeypatch.setattr(settings, "google_maps_api_key", "test-maps-key")
    monkeypatch.setattr(settings, "lta_account_key", None)
    mock_resp = MagicMock()
    mock_resp.json.return_value = _two_route_directions_payload()
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client

    with patch("capabilities.routes.journey.httpx.AsyncClient", mock_client_cls):
        default = await plan_transit_journey("Tampines MRT", "Changi Airport")
        alternative = await plan_transit_journey("Tampines MRT", "Changi Airport", route_index=1)

    assert default["route_count"] == 2
    assert default["steps"][1]["line"] == "27"
    assert alternative["route_count"] == 2
    assert alternative["steps"][1]["line"] == "12"
    # Confirms Directions is actually asked for alternatives (PR #65) rather
    # than the two calls above coincidentally returning the same mock twice.
    _, kwargs = mock_client.get.call_args
    assert kwargs["params"]["alternatives"] == "true"


@pytest.mark.asyncio
async def test_plan_transit_journey_is_honest_when_no_alternative_exists(monkeypatch):
    monkeypatch.setattr(settings, "google_maps_api_key", "test-maps-key")
    monkeypatch.setattr(settings, "lta_account_key", None)
    mock_resp = MagicMock()
    mock_resp.json.return_value = _journey_directions_payload()  # only one route
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client

    with patch("capabilities.routes.journey.httpx.AsyncClient", mock_client_cls):
        result = await plan_transit_journey("Tampines MRT", "Changi Airport", route_index=1)

    assert result["error"] == "no_alternative_available"
    assert result["route_count"] == 1


@pytest.mark.asyncio
async def test_transit_journey_tool_surfaces_route_count_for_the_agent(monkeypatch):
    """The agent (not a deterministic plugin) now decides when to ask for
    "another route" -- it can only do that honestly if the tool result tells
    it how many alternatives exist and which index it just saw."""
    from capabilities.general.tools import transit_journey

    monkeypatch.setattr(settings, "google_maps_api_key", "test-maps-key")
    monkeypatch.setattr(settings, "lta_account_key", None)
    mock_resp = MagicMock()
    mock_resp.json.return_value = _two_route_directions_payload()
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client

    with patch("capabilities.routes.journey.httpx.AsyncClient", mock_client_cls):
        text = await transit_journey.ainvoke(
            {"origin": "Tampines MRT", "destination": "Changi Airport"}
        )
    assert "2 routes available" in text
    assert "route_index=0" in text

    with patch("capabilities.routes.journey.httpx.AsyncClient", mock_client_cls):
        no_more = await transit_journey.ainvoke(
            {"origin": "Tampines MRT", "destination": "Changi Airport", "route_index": 5}
        )
    assert "No other route available" in no_more


@pytest.mark.asyncio
async def test_plan_route_transit_step_includes_bus_number(monkeypatch):
    monkeypatch.setattr(settings, "google_maps_api_key", "test-maps-key")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "status": "OK",
        "routes": [
            {
                "legs": [
                    {
                        "duration": {"value": 1800, "text": "30 mins"},
                        "distance": {"value": 12000, "text": "12.0 km"},
                        "steps": [
                            {
                                "html_instructions": "Walk to Tampines MRT",
                                "transit_details": {
                                    "line": {"short_name": "27", "name": "Tampines Int"},
                                    "departure_stop": {"name": "Tampines MRT"},
                                    "arrival_stop": {"name": "Changi Airport"},
                                },
                                "duration": {"text": "25 mins"},
                            }
                        ],
                    }
                ]
            }
        ],
    }
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    with patch("capabilities.routes.tools.httpx.AsyncClient", mock_client_cls):
        result = await plan_route.ainvoke(
            {"origin": "Tampines MRT", "destination": "Changi Airport", "mode": "transit"}
        )
    assert result["steps"][0].startswith("Take 27 from Tampines MRT to Changi Airport")


@pytest.mark.asyncio
async def test_plan_route_no_key_never_fabricates(monkeypatch):
    monkeypatch.setattr(settings, "google_maps_api_key", None)
    result = await plan_route.ainvoke({"origin": "A", "destination": "B", "mode": "transit"})
    assert result["error"] == "route_provider_not_configured"
    assert "fabricated" in result["summary"]
