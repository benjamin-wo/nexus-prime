"""Golden test for the tool catalogue.

Pins what the model sees (names, descriptions, schemas, order, exposure, which tools confirm)
and the READ_ONLY / MENU_OF / safe_for_images sets, so the tools module can be reorganised
without the catalogue changing. Regenerate on purpose with UPDATE_GOLDEN=1.
"""

import json
import os
from pathlib import Path
from typing import Any

from nexus.agent.tools import MENU_OF, READ_ONLY, build_tools, safe_for_images

FIXTURE = Path(__file__).parent / "fixtures" / "tools_catalogue.json"


def _catalogue() -> dict[str, Any]:
    tools = build_tools(lambda name: f"skill:{name}")
    return {
        "specs": [
            {
                "name": spec.name,
                "description": spec.description,
                "schema": spec.schema(),
                "exposed": spec.exposed,
                "confirms": spec.confirm is not None,
            }
            for spec in tools.values()
        ],
        "read_only": sorted(READ_ONLY),
        "menu_of": {name: str(section.value) for name, section in sorted(MENU_OF.items())},
        "safe_for_images": [spec.name for spec in tools.values() if safe_for_images(spec)],
    }


def test_catalogue_matches_golden() -> None:
    current = json.loads(json.dumps(_catalogue()))
    if os.environ.get("UPDATE_GOLDEN"):
        FIXTURE.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n")
    assert current == json.loads(FIXTURE.read_text())
