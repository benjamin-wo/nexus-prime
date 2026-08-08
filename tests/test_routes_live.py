import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from capabilities.routes import lta
from capabilities.routes.tools import (
    _bus_query_parts,
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


def test_lta_format_arrivals_shows_bus_numbers():
    text = lta.format_arrivals(
        [
            {"service": "27", "arrivals_min": [4, 12]},
            {"service": "969", "arrivals_min": [0]},
        ]
    )
    assert "Bus 27: next 4 min, then 12 min" in text
    assert "Bus 969: next due" in text


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
