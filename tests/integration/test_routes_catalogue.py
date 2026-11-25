"""Every HTTP route the app serves, with its guards: a move between files must not change it.

Regenerate on purpose with `UPDATE_GOLDEN=1 pytest tests/integration/test_routes_catalogue.py`.
"""

import json
import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from nexus.main import create_app
from nexus.settings import Settings

GOLDEN = Path(__file__).parent.parent / "fixtures" / "routes_catalogue.json"


def _dependencies(dependant: Any) -> list[str]:
    names: list[str] = []
    for sub in dependant.dependencies:
        call = sub.call
        names.append(getattr(call, "__name__", None) or type(call).__name__)
        names.extend(_dependencies(sub))
    return names


def _name(model: Any) -> str | None:
    """A model's name; a union is spelled out, without the modules its parts live in."""
    if model is None:
        return None
    return getattr(model, "__name__", None) or re.sub(r"\b(?:\w+\.)+(\w+)", r"\1", str(model))


def _api_routes(routes: Iterable[Any]) -> Iterator[APIRoute]:
    """The app's routes in matching order; routers included into it are opened up."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _api_routes(route.original_router.routes)


def _app_routes() -> list[APIRoute]:
    app = create_app(Settings(_env_file=None, database_url="postgresql://u:p@h/db"))
    return list(_api_routes(app.routes))


def _catalogue() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for route in _app_routes():
        rows.append(
            {
                "methods": sorted(route.methods or ()),
                "path": route.path,
                "endpoint": route.endpoint.__name__,
                "dependencies": sorted(set(_dependencies(route.dependant))),
                "response_model": _name(route.response_model),
                "status_code": route.status_code,
            }
        )
    return sorted(rows, key=lambda r: (r["path"], r["methods"], r["endpoint"]))


def test_the_routes_are_the_ones_on_record() -> None:
    found = _catalogue()
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(found, indent=1) + "\n")
    assert found == json.loads(GOLDEN.read_text())


def _overlap(a: str, b: str) -> bool:
    """Whether one URL could match both route paths."""
    left, right = a.split("/"), b.split("/")
    if len(left) != len(right) and not (":path}" in a or ":path}" in b):
        return False
    return all(
        x == y or x.startswith("{") or y.startswith("{") for x, y in zip(left, right, strict=False)
    )


def test_routes_that_could_match_the_same_url_keep_their_order() -> None:
    """FastAPI answers with the first route that matches, so their order is behaviour."""
    flat = [f"{m} {r.path}" for r in _app_routes() for m in sorted(r.methods or ())]
    if os.environ.get("UPDATE_GOLDEN"):
        ORDER.write_text("\n".join(flat) + "\n")
    recorded = ORDER.read_text().splitlines()
    assert sorted(flat) == sorted(recorded)
    position = {route: i for i, route in enumerate(flat)}
    for i, first in enumerate(recorded):
        for second in recorded[i + 1 :]:
            (m1, p1), (m2, p2) = first.split(" ", 1), second.split(" ", 1)
            if m1 == m2 and _overlap(p1, p2):
                assert position[first] < position[second], (first, second)


ORDER = Path(__file__).parent.parent / "fixtures" / "routes_order.txt"
