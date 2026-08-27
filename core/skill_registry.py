"""Skill + tool registry: the authoring surface is markdown.

A skill is a folder under ``skills/<name>/`` containing ``SKILL.md`` whose YAML
frontmatter declares its identity and which executable tools it uses; the body
holds the instructions an agent loads on demand. Executable tools are langchain
``@tool`` callables living in capability modules (or a skill's own tools.py)
and are resolved by name through the tool registry.

Adding a skill = dropping a folder. No registry edits, no redeploy.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

VALID_SIDE_EFFECTS = {"read", "write", "spend", "irreversible"}

# Modules whose @tool callables form the global tool surface. Skills reference
# these by name in frontmatter; the registry resolves and validates them.
TOOL_MODULES: Tuple[str, ...] = (
    "capabilities.general.tools",
    "capabilities.routes.tools",
    "capabilities.email.tools",
    "capabilities.expenses.tools",
    "capabilities.recipes.tools",
    "capabilities.reminders.tools",
    "capabilities.whiteboard.tools",
    "capabilities.memory.tools",
    "capabilities.bug_logging.tools",
    "capabilities.scheduled_content_delivery.tools",
    "capabilities.code_exec.tools",
    "orchestrator.recipes",
)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    tags: Tuple[str, ...]
    side_effect: str
    tools: Tuple[str, ...]
    body: str
    path: str

    @property
    def index_line(self) -> str:
        """One-line entry for the agent's skill index (system prompt)."""
        tools = ", ".join(self.tools) if self.tools else "none"
        return f"- {self.name} [{self.side_effect}]: {self.description} (tools: {tools})"


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Split a markdown file into (frontmatter dict, body). No frontmatter → ({}, text)."""
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", text, re.DOTALL)
    if not match:
        return {}, text.strip()
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, match.group(2).strip()
    if not isinstance(data, dict):
        return {}, match.group(2).strip()
    return data, match.group(2).strip()


def load_skill_file(path: Path) -> Optional[Skill]:
    raw = path.read_text(encoding="utf-8")
    data, body = parse_frontmatter(raw)
    name = str(data.get("name") or path.parent.name if path.name == "SKILL.md" else path.stem).strip()
    description = str(data.get("description") or "").strip()
    if not name or not description:
        return None
    side_effect = str(data.get("side_effect") or "read").strip().lower()
    if side_effect not in VALID_SIDE_EFFECTS:
        side_effect = "read"
    tags = tuple(str(t).strip() for t in (data.get("tags") or []) if str(t).strip())
    tools = tuple(str(t).strip().lstrip("#") for t in (data.get("tools") or []) if str(t).strip())
    return Skill(
        name=name,
        description=description,
        tags=tags,
        side_effect=side_effect,
        tools=tools,
        body=body,
        path=str(path),
    )


def discover_skills(skills_dir: Optional[Path] = None) -> Dict[str, Skill]:
    """Load every SKILL.md under the skills directory (dir-per-skill or flat)."""
    root = Path(skills_dir) if skills_dir else SKILLS_DIR
    skills: Dict[str, Skill] = {}
    if not root.exists():
        return skills
    candidates: List[Path] = []
    for path in sorted(root.rglob("*.md")):
        if path.name in {"SKILL.md", "skill.md"} or path.parent == root:
            candidates.append(path)
    for path in candidates:
        skill = load_skill_file(path)
        if skill is None:
            continue
        if skill.name in skills:
            continue  # first definition wins; folders are sorted deterministically
        skills[skill.name] = skill
    return skills


_TOOL_CACHE: Optional[Dict[str, Any]] = None


def build_tool_registry(force: bool = False) -> Dict[str, Any]:
    """Import tool modules and index every @tool callable by name."""
    global _TOOL_CACHE
    if _TOOL_CACHE is not None and not force:
        return _TOOL_CACHE
    registry: Dict[str, Any] = {}
    for module_path in TOOL_MODULES:
        try:
            module = importlib.import_module(module_path)
        except Exception as exc:  # noqa: BLE001 - a broken optional module must not kill the registry
            print(f"[SKILLS] failed to import tool module {module_path}: {exc}")
            continue
        for attr in vars(module).values():
            if getattr(attr, "name", None) and callable(getattr(attr, "ainvoke", None)):
                registry.setdefault(str(attr.name), attr)
    # A skill's own tools.py, when present, is loaded lazily via
    # load_skill_tools(); name collisions with core modules are ignored here.
    _TOOL_CACHE = registry
    return registry


def load_skill_tools(skill: Skill) -> Dict[str, Any]:
    """Load tools declared by a skill: core registry hits plus the skill's
    own tools.py (imported as skills.<name>.tools) when present."""
    registry = dict(build_tool_registry())
    tools_dir = Path(skill.path).parent
    own_tools = tools_dir / "tools.py"
    if own_tools.exists():
        module_path = f"skills.{tools_dir.name}.tools"
        try:
            module = importlib.import_module(module_path)
        except Exception as exc:  # noqa: BLE001
            print(f"[SKILLS] failed to import {module_path}: {exc}")
            module = None
        if module is not None:
            for attr in vars(module).values():
                if getattr(attr, "name", None) and callable(getattr(attr, "ainvoke", None)):
                    registry.setdefault(str(attr.name), attr)
    return registry


def resolve_skill_tools(skill: Skill) -> List[Any]:
    """Resolve a skill's declared tool names to callables (missing ones warn)."""
    available = load_skill_tools(skill)
    resolved: List[Any] = []
    for tool_name in skill.tools:
        tool_obj = available.get(tool_name)
        if tool_obj is None:
            print(f"[SKILLS] skill {skill.name!r} references unknown tool {tool_name!r}")
            continue
        resolved.append(tool_obj)
    return resolved


def all_declared_tools(skills: Dict[str, Skill]) -> List[Any]:
    """Every tool declared by any skill, deduplicated, in declaration order."""
    registry = build_tool_registry()
    resolved: List[Any] = []
    seen: set[str] = set()
    for skill in skills.values():
        for tool_obj in resolve_skill_tools(skill):
            if tool_obj.name in seen:
                continue
            seen.add(tool_obj.name)
            resolved.append(tool_obj)
    # Guard against registry drift: tools loaded but not declared by any skill
    # stay available to the agent so a forgotten frontmatter line never
    # silently removes a capability.
    declared = {t.name for t in resolved}
    for name, tool_obj in registry.items():
        if name not in declared and name not in {"search_email_messages", "search_gmail_messages", "search_outlook_messages", "apply_email_processed_tag", "apply_gmail_processed_label", "apply_outlook_processed_category", "get_user_expenses", "log_expenses_from_emails", "run_python_code"}:
            resolved.append(tool_obj)
    return resolved


def skill_index_text(skills: Dict[str, Skill]) -> str:
    """Compact skill index for the agent system prompt."""
    if not skills:
        return "(no skills installed)"
    return "\n".join(skill.index_line for skill in skills.values())


def make_load_skill_tool(skills_provider):
    """Build the progressive-disclosure tool: the agent pulls a skill's full
    instruction body into context when the index says it's relevant."""
    from langchain_core.tools import tool

    @tool
    def load_skill(name: str) -> str:
        """
        Load the full instructions for a skill by name (from the skill index).
        Call this BEFORE using a skill's tools when the task matches the skill's
        description, so you follow its exact how-to guidance.
        """
        skills = skills_provider()
        skill = skills.get((name or "").strip())
        if skill is None:
            known = ", ".join(sorted(skills)) or "none installed"
            return f"[skills] No skill named {name!r}. Installed: {known}."
        header = f"# Skill: {skill.name} [{skill.side_effect}]\n{skill.description}\n"
        return f"{header}\n{skill.body}"

    return load_skill
