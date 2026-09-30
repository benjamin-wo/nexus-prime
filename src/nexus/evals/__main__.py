"""Score models on the evaluation set.

    OPENROUTER_API_KEY=... EVAL_DATABASE_URL=postgresql://user:pass@host/postgres \\
      python -m nexus.evals --model deepseek/deepseek-chat --model google/gemini-2.5-flash

Each run creates a throwaway database on EVAL_DATABASE_URL's server (the user must
be allowed to CREATE DATABASE), migrates it, and drops it afterwards. Results go
to eval-results/ as JSON and Markdown. The key is read from the environment and
never printed. Every case uses made-up data only.
"""

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import asyncpg
import httpx
from alembic import command
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from nexus.evals.cases import CASES, Case
from nexus.evals.runner import CaseResult, Pricing, Summary, run_cases
from nexus.infra.db.engine import make_engine
from nexus.infra.db.migrations import alembic_config

OPENROUTER = "https://openrouter.ai/api/v1"


def openrouter_model(name: str, api_key: str, timeout: float = 90.0) -> BaseChatModel:
    return ChatOpenAI(
        model=name,
        api_key=SecretStr(api_key),
        base_url=OPENROUTER,
        temperature=0.0,
        timeout=timeout,
        max_retries=2,
        default_headers={"X-Title": "Nexus Prime evals"},
    )


async def pricing(models: list[str]) -> dict[str, Pricing]:
    """Per-token prices from OpenRouter's public model list; empty if unreachable."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{OPENROUTER}/models")
            response.raise_for_status()
    except httpx.HTTPError:
        return {}
    found: dict[str, Pricing] = {}
    for item in response.json().get("data", []):
        if item.get("id") in models and item.get("pricing"):
            p = item["pricing"]
            found[item["id"]] = Pricing(Decimal(p["prompt"]), Decimal(p["completion"]))
    return found


@asynccontextmanager
async def throwaway_database(admin_url: str) -> AsyncIterator[str]:
    admin = make_url(admin_url).set(drivername="postgresql")
    name = f"nexus_eval_{uuid.uuid4().hex[:10]}"
    dsn = admin.render_as_string(hide_password=False)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()
    try:
        url = admin.set(drivername="postgresql+asyncpg", database=name)
        yield url.render_as_string(hide_password=False)
    finally:
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await conn.close()


def _pick(ids: list[str], areas: list[str]) -> list[Case]:
    cases = [
        c
        for c in CASES
        if (not ids or any(c.id.startswith(i) for i in ids)) and (not areas or c.area in areas)
    ]
    if not cases:
        sys.exit("no cases match")
    return cases


def _as_json(result: CaseResult) -> dict[str, object]:
    return {
        "id": result.case.id,
        "area": result.case.area,
        "target": result.case.target,
        "passed": result.passed,
        "failures": result.failures,
        "error": result.error,
        "turns": [
            {
                "text": t.text,
                "replies": t.replies,
                "calls": [{"tool": n, "args": a} for n, a in t.calls],
                "confirmations": t.confirmations,
                "seconds": round(t.seconds, 2),
                "input_tokens": t.input_tokens,
                "output_tokens": t.output_tokens,
                "memory_input_tokens": t.memory_input_tokens,
                "memory_output_tokens": t.memory_output_tokens,
                "memory_failed": t.memory_failed,
            }
            for t in result.turns
        ],
    }


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nexus.evals", description=__doc__)
    parser.add_argument("--model", action="append", required=True, help="OpenRouter model id")
    parser.add_argument("--case", action="append", default=[], help="case id or id prefix")
    parser.add_argument("--area", action="append", default=[])
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--vision-model", help="another model for receipt photos (default: each --model)"
    )
    parser.add_argument(
        "--memory-model", help="another model for the memory writer (default: each --model)"
    )
    parser.add_argument("--out", default="eval-results")
    args = parser.parse_args(argv)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    admin_url = os.environ.get("EVAL_DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not api_key:
        sys.exit("OPENROUTER_API_KEY is not set")
    if not admin_url:
        sys.exit("EVAL_DATABASE_URL is not set")

    cases = _pick(args.case, args.area)
    prices = await pricing([*args.model, *([args.memory_model] if args.memory_model else [])])
    out = Path(args.out)
    await asyncio.to_thread(out.mkdir, parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    summaries: list[Summary] = []

    async with throwaway_database(admin_url) as url:
        await asyncio.to_thread(_migrate, url)
        engine = make_engine(url)
        try:
            for offset, name in enumerate(args.model):
                model = openrouter_model(name, api_key)
                print(f"{name}: {len(cases)} cases", flush=True)

                def progress(result: CaseResult) -> None:
                    mark = "." if result.passed else "F"
                    print(mark, end="", flush=True)

                results = await run_cases(
                    engine,
                    _always(model),
                    cases,
                    concurrency=args.concurrency,
                    first_telegram_id=1_000_000 + offset * 10_000,
                    on_result=progress,
                    vision=openrouter_model(args.vision_model, api_key)
                    if args.vision_model
                    else None,
                    memory=openrouter_model(args.memory_model, api_key)
                    if args.memory_model
                    else None,
                )
                print(flush=True)
                label = name
                if args.vision_model:
                    label += f" + {args.vision_model} (photos)"
                if args.memory_model:
                    label += f" + {args.memory_model} (memory)"
                memory_price = prices.get(args.memory_model) if args.memory_model else None
                summary = Summary(label, results, prices.get(name), memory_price)
                summaries.append(summary)
                safe = name.replace("/", "_").replace(":", "_")
                await _write(
                    out / f"{stamp}-{safe}.json",
                    json.dumps([_as_json(r) for r in results], indent=2, default=str),
                )
                print(f"{name}: {summary.passed}/{len(results)} passed", flush=True)
        finally:
            await engine.dispose()

    report = "\n\n".join(s.markdown() for s in summaries)
    await _write(out / f"{stamp}-report.md", report + "\n")
    print(report)
    return 0


def _always(model: BaseChatModel) -> Callable[[Case], BaseChatModel]:
    def model_for(_case: Case) -> BaseChatModel:
        return model

    return model_for


async def _write(path: Path, text: str) -> None:
    await asyncio.to_thread(path.write_text, text)


def _migrate(url: str) -> None:
    config = alembic_config(url)
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
