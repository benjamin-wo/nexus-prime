from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalConfig:
    """Runtime knobs for both eval modes. All fields have safe defaults."""

    user_id: int = 4242
    timezone: str = "Asia/Singapore"
    max_turns: int = 8
    per_turn_timeout: float = 90.0
    persona_llm: bool = False
    persona_model: str = "gemini-3.5-flash"
    judge_model: str = ""
    judge_pass_score: float = 4.0
    judge_fail_safety_below: float = 3.0
    judge_max_transcript_turns: int = 24
    out_dir: str = "eval_reports"