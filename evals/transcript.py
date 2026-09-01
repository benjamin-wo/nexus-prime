from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path


@dataclass
class Turn:
    role: str
    text: str


@dataclass
class Conversation:
    id: str
    scenario_id: str
    turns: List[Turn] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "scenario_id": self.scenario_id,
            "turns": [{"role": t.role, "text": t.text} for t in self.turns],
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conversation":
        return cls(
            id=str(data.get("id") or ""),
            scenario_id=str(data.get("scenario_id") or ""),
            turns=[Turn(role=str(t.get("role") or ""), text=str(t.get("text") or "")) for t in data.get("turns", [])],
            meta=data.get("meta") or {},
        )


def save_conversations(path: Path, conversations: List[Conversation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for conv in conversations:
            fh.write(json.dumps(conv.to_dict(), ensure_ascii=False) + "\n")


def load_conversations(path: Path) -> List[Conversation]:
    conversations: List[Conversation] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                conversations.append(Conversation.from_dict(json.loads(line)))
    return conversations