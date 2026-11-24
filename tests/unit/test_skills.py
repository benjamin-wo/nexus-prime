from pathlib import Path

import pytest

from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools
from nexus.domain.errors import NotFound


def test_bundled_skills_load_and_name_real_tools() -> None:
    library = SkillLibrary.load()
    tools = build_tools(library.body)
    library.validate_tools(set(tools))
    assert "- expenses:" in library.index()
    assert "## Splitting" in library.body("expenses")
    gym = library.tools()["gym"]
    assert {"log_sets", "finish_workout", "undo_last_set", "last_time"} <= set(gym)
    assert "Finance expense" in library.body("gym") and "qualified professional" in library.body(
        "gym"
    )
    assert set(library.tools()["nutrition"]) == {"log_food", "food_today"}
    nutrition = library.body("nutrition")
    assert (
        "Finance" in nutrition and "log_expense" in nutrition and "Singapore database" in nutrition
    )
    with pytest.raises(NotFound):
        library.body("nope")


def test_rejects_unknown_tools_and_mismatched_names(tmp_path: Path) -> None:
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: demo\ndescription: d\ntools: [ghost]\n---\nbody")
    with pytest.raises(ValueError, match="ghost"):
        SkillLibrary.load(tmp_path).validate_tools({"log_expense"})
    (folder / "SKILL.md").write_text("---\nname: other\n---\nbody")
    with pytest.raises(ValueError, match="folder"):
        SkillLibrary.load(tmp_path)


def test_hidden_tools_are_not_offered_to_the_model() -> None:
    tools = build_tools(lambda _: "")
    assert not tools["log_receipt_expense"].exposed
    schema = tools["log_expense"].schema()
    assert "user_id" not in schema["function"]["parameters"]["properties"]


def test_tool_schemas_convert_for_gemini_without_refs() -> None:
    from langchain_google_genai._function_utils import convert_to_genai_function_declarations

    schemas = [s.schema() for s in build_tools(lambda _: "").values() if s.exposed]
    assert "$ref" not in str(schemas) and "$defs" not in str(schemas)
    converted = convert_to_genai_function_declarations(schemas)
    tools = converted if isinstance(converted, list) else [converted]
    names = {f.name for t in tools for f in t.function_declarations or []}
    assert names == {s["function"]["name"] for s in schemas}
    split = next(f for t in tools for f in t.function_declarations or [] if f.name == "split_bill")
    assert split.parameters is not None
    participants = split.parameters.properties["participants"]  # type: ignore[index]
    assert participants.items.required == ["name"]  # type: ignore[union-attr]
