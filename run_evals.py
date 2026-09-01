#!/usr/bin/env python3
"""Run the 4-tier chatbot evaluation framework (Tiers 3-4) for Nexus Prime.

Tier 1-2 (deterministic unit + trajectory tests) are plain pytest suites:
    pytest tests/unit
    pytest tests/trajectories

Tier 3 (multi-turn simulation) and Tier 4 (LLM-as-judge):
    python run_evals.py --mode simulation
    python run_evals.py --mode judge --transcripts eval_reports/simulation.jsonl
    python run_evals.py --mode all

Exit codes: 0 = all passed, 1 = metric failures, 2 = infrastructure/usage error.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from core.config import settings

from evals.config import EvalConfig
from evals.judge import aggregate_judgments, build_judge_llm, judge_conversation
from evals.report import build_json_report, render_combined
from evals.scenarios import resolve_scenarios
from evals.simulation import run_scenarios
from evals.transcript import load_conversations, save_conversations


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_evals.py",
        description="Tier 3-4 chatbot evaluation harness (simulation + LLM-as-judge).",
    )
    parser.add_argument("--mode", choices=["simulation", "judge", "all"], default="simulation")
    parser.add_argument("--scenarios", default="all", help="comma-separated scenario ids or 'all'")
    parser.add_argument("--scenario-files", default="", help="comma-separated JSON scenario files")
    parser.add_argument("--transcripts", default="", help="JSONL transcript file(s) for judge mode")
    parser.add_argument("--out", default="", help="output directory (default eval_reports/<timestamp>)")
    parser.add_argument("--user-id", type=int, default=4242)
    parser.add_argument("--timezone", default="Asia/Singapore")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--per-turn-timeout", type=float, default=90.0)
    parser.add_argument("--persona-llm", action="store_true", help="drive persona scenarios with an LLM")
    parser.add_argument("--persona-model", default="gemini-3.5-flash")
    parser.add_argument("--judge-model", default="", help="override settings.gemini_judge_model")
    parser.add_argument("--judge-pass", type=float, default=4.0)
    parser.add_argument("--judge-safety-min", type=float, default=3.0)
    parser.add_argument("--json", action="store_true", help="print JSON report to stdout")
    return parser.parse_args(argv)


def _out_dir(args: argparse.Namespace) -> Path:
    if args.out:
        return Path(args.out)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("eval_reports") / stamp


async def _run_simulation(args: argparse.Namespace, out_dir: Path) -> List:
    from core.db import init_db

    await init_db()
    scenario_files = [Path(p) for p in args.scenario_files.split(",") if p.strip()]
    scenarios = resolve_scenarios(
        [s.strip() for s in args.scenarios.split(",") if s.strip()],
        extra_files=scenario_files,
    )
    cfg = EvalConfig(
        user_id=args.user_id,
        timezone=args.timezone,
        max_turns=args.max_turns,
        per_turn_timeout=args.per_turn_timeout,
        persona_llm=args.persona_llm,
        persona_model=args.persona_model,
    )
    if not settings.has_llm_key:
        print("WARNING: no LLM key configured (GEMINI_API_KEY/DEEPSEEK_API_KEY); "
              "scripted turns will hit the no-key canned reply path.", file=sys.stderr)
    results = await run_scenarios(scenarios, cfg)
    conversations = [r.conversation for r in results if r.conversation is not None]
    transcripts_path = out_dir / "simulation.jsonl"
    save_conversations(transcripts_path, conversations)
    return results, transcripts_path


async def _run_judge(args: argparse.Namespace, transcript_paths: List[Path], out_dir: Path) -> dict:
    conversations = []
    for path in transcript_paths:
        if not path.exists():
            raise FileNotFoundError(f"transcript file not found: {path}")
        conversations.extend(load_conversations(path))
    if not conversations:
        raise ValueError("no conversations found in the given transcript files")
    cfg = EvalConfig(
        judge_model=args.judge_model,
        judge_pass_score=args.judge_pass,
        judge_fail_safety_below=args.judge_safety_min,
        per_turn_timeout=args.per_turn_timeout,
    )
    judge_llm = build_judge_llm(args.judge_model)
    judgments = [await judge_conversation(conv, judge_llm, cfg) for conv in conversations]
    report = aggregate_judgments(judgments, cfg)
    report["pass_score"] = cfg.judge_pass_score
    report["fail_safety_below"] = cfg.judge_fail_safety_below
    report["judgments"] = judgments
    (out_dir / "judge.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


async def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    out_dir = _out_dir(args)
    out_dir.mkdir(parents=True, exist_ok=True)

    sim_results: List = []
    judge_report: dict = {}
    transcripts_path: Optional[Path] = None

    if args.mode in ("simulation", "all"):
        sim_results, transcripts_path = await _run_simulation(args, out_dir)

    if args.mode in ("judge", "all"):
        transcript_paths = [Path(p) for p in args.transcripts.split(",") if p.strip()]
        if args.mode == "all":
            if transcripts_path is None or not transcripts_path.exists():
                print("ERROR: --mode all needs a successful simulation run first.", file=sys.stderr)
                return 2
            transcript_paths = [transcripts_path]
        if not transcript_paths:
            print("ERROR: judge mode requires --transcripts <file.jsonl>.", file=sys.stderr)
            return 2
        try:
            judge_report = await _run_judge(args, transcript_paths, out_dir)
        except (FileNotFoundError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    text_report = render_combined(sim_results, judge_report)
    print(text_report)
    (out_dir / "summary.txt").write_text(text_report, encoding="utf-8")
    if args.json:
        print(json.dumps(build_json_report(sim_results, judge_report), indent=2, ensure_ascii=False))

    failed_sim = any(r.status != "passed" for r in sim_results)
    failed_judge = bool(judge_report) and not judge_report.get("all_passed", False)
    if failed_sim or failed_judge:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))