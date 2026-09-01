from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TurnCheck:
    contains: List[str] = field(default_factory=list)
    not_contains: List[str] = field(default_factory=list)


@dataclass
class ContextCheck:
    turn: int
    terms: List[str] = field(default_factory=list)


@dataclass
class Scenario:
    id: str
    name: str
    description: str = ""
    user_turns: List[str] = field(default_factory=list)
    checks: List[TurnCheck] = field(default_factory=list)
    context_checks: List[ContextCheck] = field(default_factory=list)
    expected_tools: List[str] = field(default_factory=list)
    forbidden_tools: List[str] = field(default_factory=list)
    persona: Optional[str] = None
    max_turns: int = 6
    tags: List[str] = field(default_factory=list)

    @property
    def is_persona(self) -> bool:
        return bool(self.persona)


BUILTIN_SCENARIOS: List[Scenario] = [
    Scenario(
        id="expense_log",
        name="Log an expense from text",
        description="User reports a lunch expense; bot must extract amount and confirm.",
        user_turns=["Spent $15.50 on lunch at the hawker centre"],
        checks=[TurnCheck(contains=["15.50"], not_contains=["error", "sorry"])],
        expected_tools=["process_extracted_expense"],
        tags=["expenses"],
    ),
    Scenario(
        id="expense_delete",
        name="Delete an expense by merchant",
        description="User asks to delete an expense; bot must find it then call delete_expense.",
        user_turns=["Can you delete the coinhako expense"],
        checks=[TurnCheck(contains=["Coinhako"], not_contains=["can't", "cannot", "not able"])],
        expected_tools=["get_user_expenses", "delete_expense"],
        tags=["expenses"],
    ),
    Scenario(
        id="greeting_no_tools",
        name="Greeting must not call tools",
        description="A bare greeting should short-circuit deterministically with zero tool calls.",
        user_turns=["hi"],
        checks=[TurnCheck(contains=["hey", "Hey", "hi", "Hi"], not_contains=["error", "sorry"])],
        forbidden_tools=["search_web", "get_user_expenses", "list_my_reminders", "list_my_boards"],
        tags=["kernel"],
    ),
    Scenario(
        id="expense_edit",
        name="Edit an expense by merchant",
        description="User corrects an expense; bot must edit it, not re-log a duplicate.",
        user_turns=["Actually change the coinhako expense to 12.50"],
        checks=[TurnCheck(not_contains=["can't", "cannot", "not able"])],
        expected_tools=["get_user_expenses", "edit_expense"],
        tags=["expenses"],
    ),
    Scenario(
        id="expense_undo",
        name="Undo the last expense write",
        description="User wants to revert the most recent expense write.",
        user_turns=["undo that last expense"],
        checks=[TurnCheck(not_contains=["can't", "cannot", "not able"])],
        expected_tools=["undo_last_write"],
        tags=["expenses"],
    ),
    Scenario(
        id="out_of_scope_refusal",
        name="Out-of-scope request handled honestly",
        description="Bot must not fake success for something no tool can do.",
        user_turns=["book me a flight to tokyo"],
        checks=[TurnCheck(not_contains=["booked", "confirmed", "done!", "reserved"])],
        tags=["honesty"],
    ),
    Scenario(
        id="income_log",
        name="Log incoming money",
        description="User reports salary; bot must record it as incoming money.",
        user_turns=["Got my salary of $4200 today"],
        checks=[TurnCheck(contains=["4200"], not_contains=["error", "sorry"])],
        expected_tools=["record_incoming_money"],
        tags=["income"],
    ),
    Scenario(
        id="transaction_query",
        name="Query transaction history",
        description="User asks about past spending; bot must look up the ledger.",
        user_turns=["How much did I spend on dining last month?"],
        checks=[TurnCheck(not_contains=["error", "sorry"])],
        expected_tools=["query_transactions", "get_user_expenses"],
        tags=["ledger"],
    ),
    Scenario(
        id="multi_turn_correction",
        name="Multi-turn correction with context retention",
        description="User logs an expense, then corrects the amount; bot must remember the prior turn.",
        user_turns=[
            "Log $20 for dinner at Sakura",
            "Actually make that $25 instead",
        ],
        checks=[
            TurnCheck(contains=["20"], not_contains=["error"]),
            TurnCheck(contains=["25"], not_contains=["error"]),
        ],
        context_checks=[ContextCheck(turn=1, terms=["Sakura"])],
        expected_tools=["process_extracted_expense"],
        tags=["expenses", "multi_turn"],
    ),
    Scenario(
        id="reminder_create",
        name="Create a one-time reminder",
        description="User asks for a reminder; bot must create a scheduled job.",
        user_turns=["Remind me to buy milk at 6pm tonight"],
        checks=[TurnCheck(contains=["milk"], not_contains=["error", "sorry"])],
        expected_tools=["create_one_time_reminder"],
        tags=["reminders"],
    ),
    Scenario(
        id="termination_kernel",
        name="Termination intent hits the deterministic kernel",
        description="'stop' must short-circuit in the kernel, never reaching the LLM.",
        user_turns=["stop"],
        checks=[TurnCheck(contains=["stop"])],
        tags=["kernel"],
    ),
    Scenario(
        id="persona_expense_flow",
        name="Persona-driven expense flow",
        description="A simulated user logs an expense then reviews dining spend.",
        persona=(
            "You are Ben, a busy Singapore-based professional. You are concise and "
            "slightly informal. GOAL: (1) log a lunch expense of around $15-20, then "
            "(2) ask how much you spent on dining this month."
        ),
        max_turns=8,
        tags=["expenses", "persona"],
    ),
]


def get_scenario(scenario_id: str) -> Optional[Scenario]:
    for scenario in BUILTIN_SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    return None


def load_scenarios(path: Path) -> List[Scenario]:
    """Load additional scenarios from a JSON file (same shape as the dataclasses)."""
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    scenarios: List[Scenario] = []
    for raw in data if isinstance(data, list) else data.get("scenarios", []):
        scenarios.append(
            Scenario(
                id=str(raw["id"]),
                name=str(raw.get("name") or raw["id"]),
                description=str(raw.get("description") or ""),
                user_turns=[str(t) for t in raw.get("user_turns", [])],
                checks=[
                    TurnCheck(
                        contains=[str(t) for t in c.get("contains", [])],
                        not_contains=[str(t) for t in c.get("not_contains", [])],
                    )
                    for c in raw.get("checks", [])
                ],
                context_checks=[
                    ContextCheck(turn=int(c["turn"]), terms=[str(t) for t in c.get("terms", [])])
                    for c in raw.get("context_checks", [])
                ],
                expected_tools=[str(t) for t in raw.get("expected_tools", [])],
                forbidden_tools=[str(t) for t in raw.get("forbidden_tools", [])],
                persona=(str(raw["persona"]) if raw.get("persona") else None),
                max_turns=int(raw.get("max_turns") or 6),
                tags=[str(t) for t in raw.get("tags", [])],
            )
        )
    return scenarios


def resolve_scenarios(ids: Optional[List[str]], extra_files: Optional[List[Path]] = None) -> List[Scenario]:
    """Resolve a scenario-id list ('all' = every builtin) plus any JSON files."""
    extra: Dict[str, Scenario] = {}
    for path in extra_files or []:
        for scenario in load_scenarios(path):
            extra[scenario.id] = scenario
    all_scenarios = {s.id: s for s in BUILTIN_SCENARIOS}
    all_scenarios.update(extra)
    if not ids:
        return list(all_scenarios.values())
    resolved: List[Scenario] = []
    for raw_id in ids:
        if raw_id == "all":
            return list(all_scenarios.values())
        scenario = all_scenarios.get(raw_id)
        if scenario is None:
            raise ValueError(f"Unknown scenario: {raw_id}")
        resolved.append(scenario)
    return resolved