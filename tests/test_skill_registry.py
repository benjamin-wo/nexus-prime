"""The skill registry: SKILL.md frontmatter is the authoring surface."""
import textwrap
from pathlib import Path

from core.skill_registry import (
    Skill,
    build_tool_registry,
    discover_skills,
    load_skill_file,
    make_load_skill_tool,
    parse_frontmatter,
    resolve_skill_tools,
    skill_index_text,
)


def test_parse_frontmatter_basic():
    data, body = parse_frontmatter(
        "---\nname: transit\ndescription: Live bus times\ntools:\n  - get_bus_timings\n---\n\n# Body here\n"
    )
    assert data["name"] == "transit"
    assert data["tools"] == ["get_bus_timings"]
    assert "# Body here" in body


def test_parse_frontmatter_missing_returns_empty():
    data, body = parse_frontmatter("# just markdown\nno frontmatter")
    assert data == {}
    assert "no frontmatter" in body


def test_load_skill_file(tmp_path: Path):
    skill_dir = tmp_path / "transit"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: transit
            description: Live Singapore bus times
            tags: [transit, bus]
            side_effect: read
            tools:
              - get_bus_timings
              - not_a_real_tool
            ---

            # How to answer bus asks
            """
        )
    )
    skill = load_skill_file(skill_dir / "SKILL.md")
    assert skill is not None
    assert skill.name == "transit"
    assert skill.side_effect == "read"
    assert skill.tools == ("get_bus_timings", "not_a_real_tool")
    assert "How to answer bus asks" in skill.body


def test_discover_skills_from_repo():
    skills = discover_skills()
    names = set(skills)
    assert {
        "web-research", "expenses", "transit", "email", "reminders",
        "recipes-groceries", "memory", "bug-logging", "daily-briefing",
        "whiteboard-planning", "code-exec", "composed-recipes",
    } <= names


def test_tool_registry_resolves_declared_tools():
    registry = build_tool_registry()
    assert "search_web" in registry
    assert "get_bus_timings" in registry
    assert "log_expense" in registry
    assert "create_reminder" in registry
    assert "run_recipe" in registry

    skills = discover_skills()
    transit = skills["transit"]
    resolved = resolve_skill_tools(transit)
    resolved_names = {t.name for t in resolved}
    assert {"get_bus_timings", "transit_journey", "plan_route", "extract_route_request"} <= resolved_names


def test_skill_index_lists_every_skill():
    skills = discover_skills()
    index = skill_index_text(skills)
    for name in skills:
        assert name in index


def test_load_skill_tool_returns_body():
    skills = discover_skills()
    tool = make_load_skill_tool(lambda: skills)
    result = tool.invoke({"name": "transit"})
    assert "Bus timings & routes" in result
    assert "NEVER fabricate a bus number" in result

    miss = tool.invoke({"name": "does-not-exist"})
    assert "No skill named" in miss


def test_skill_side_effect_defaults_to_read(tmp_path: Path):
    skill_dir = tmp_path / "mystery"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: mystery\ndescription: no side effect declared\n---\nbody")
    skill = load_skill_file(skill_dir / "SKILL.md")
    assert skill.side_effect == "read"
