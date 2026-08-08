import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from capabilities.routes import lta
from capabilities.routes.journey import format_journey, plan_transit_journey
from capabilities.routes.tools import (
    _bus_query_parts,
    _selection_intent,
    handle_bus_query,
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
