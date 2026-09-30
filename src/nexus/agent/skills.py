"""Skills: ``skills/<name>/SKILL.md`` with YAML frontmatter, loaded on demand."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from nexus.domain.errors import NotFound

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    tools: tuple[str, ...]
    body: str


def _parse(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing frontmatter")
    front, _, body = text[4:].partition("\n---\n")
    meta = yaml.safe_load(front) or {}
    name = str(meta.get("name", ""))
    if name != path.parent.name:
        raise ValueError(f"{path}: name {name!r} must match its folder")
    return Skill(
        name=name,
        description=str(meta.get("description", "")).strip(),
        tools=tuple(meta.get("tools") or ()),
        body=body.strip(),
    )


class SkillLibrary:
    def __init__(self, skills: dict[str, Skill]) -> None:
        self._skills = skills

    @classmethod
    def load(cls, directory: Path = SKILLS_DIR) -> "SkillLibrary":
        skills = [_parse(p) for p in sorted(directory.glob("*/SKILL.md"))]
        return cls({s.name: s for s in skills})

    def validate_tools(self, known: set[str]) -> None:
        for skill in self._skills.values():
            unknown = set(skill.tools) - known
            if unknown:
                raise ValueError(f"skill {skill.name!r} names unknown tools {sorted(unknown)}")

    def tools(self) -> dict[str, tuple[str, ...]]:
        """Each skill's tools, which the model is offered once it loads the skill."""
        return {s.name: s.tools for s in self._skills.values()}

    def index(self) -> str:
        return "\n".join(
            f"- {s.name}: {s.description} Tools: {', '.join(s.tools)}."
            for s in self._skills.values()
        )

    def body(self, name: str) -> str:
        skill = self._skills.get(name.strip().lower())
        if skill is None:
            raise NotFound(f"no skill called {name!r}")
        return skill.body
