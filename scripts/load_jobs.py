"""Load check for the job runner (M10): throughput, exactly-once and backlog.

    TEST_DATABASE_URL=postgresql://user:pass@localhost/postgres \\
      python scripts/load_jobs.py --jobs 2000 --runners 3 --work-ms 20

Creates a throwaway database, migrates it, queues the jobs, runs the runners
until the queue is empty (or --seconds passes), checks every job ran exactly
once, and prints the numbers. Nothing touches a real database.
"""

import argparse
import asyncio
import os
import time
import uuid
from collections import Counter
from typing import Any

import asyncpg
from alembic import command
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from nexus.application.clock import utcnow
from nexus.infra.db.engine import make_engine
from nexus.infra.db.migrations import alembic_config
from nexus.infra.db.tables import jobs
from nexus.infra.db.uow import SqlUnitOfWork
from nexus.jobs.runner import JobRunner


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=2000)
    parser.add_argument("--runners", type=int, default=3)
    parser.add_argument("--work-ms", type=float, default=20.0, help="each job's simulated work")
    parser.add_argument("--slow-every", type=int, default=0, help="every Nth job takes 10x")
    parser.add_argument("--seconds", type=float, default=300.0)
    parser.add_argument("--interval", type=float, default=5.0, help="the runner's idle wait")
    args = parser.parse_args()

    admin = make_url(os.environ["TEST_DATABASE_URL"]).set(drivername="postgresql")
    name = f"nexus_load_{uuid.uuid4().hex[:8]}"
    dsn = admin.render_as_string(hide_password=False)
    conn = await asyncpg.connect(dsn)
    await conn.execute(f'CREATE DATABASE "{name}"')
    await conn.close()
    url = admin.set(drivername="postgresql+asyncpg", database=name).render_as_string(
        hide_password=False
    )
    try:
        config = alembic_config(url)
        config.attributes["configure_logger"] = False
        await asyncio.to_thread(command.upgrade, config, "head")
        engine = make_engine(url)
        runs: Counter[int] = Counter()

        async def work(payload: dict[str, Any]) -> None:
            n = int(payload["n"])
            runs[n] += 1
            slow = args.slow_every and n % args.slow_every == 0
            await asyncio.sleep(args.work_ms / 1000 * (10 if slow else 1))

        start = utcnow()
        async with SqlUnitOfWork(engine) as tx:
            for n in range(args.jobs):
                await tx.jobs.enqueue("load", {"n": n}, dedupe_key=f"load-{n}", run_at=start)
            await tx.commit()

        stop = asyncio.Event()
        runners = [JobRunner(engine, {"load": work}) for _ in range(args.runners)]
        began = time.perf_counter()
        tasks = [asyncio.create_task(r.run(stop, interval=args.interval)) for r in runners]

        async def remaining() -> int:
            async with engine.connect() as db:
                return int(
                    (
                        await db.execute(
                            select(func.count()).select_from(jobs).where(jobs.c.status != "done")
                        )
                    ).scalar_one()
                )

        left = args.jobs
        while left and time.perf_counter() - began < args.seconds:
            await asyncio.sleep(0.5)
            left = await remaining()
        elapsed = time.perf_counter() - began
        stop.set()
        await asyncio.gather(*tasks)
        await engine.dispose()

        done = args.jobs - left
        twice = sum(1 for c in runs.values() if c > 1)
        print(
            f"jobs={args.jobs} runners={args.runners} work={args.work_ms}ms "
            f"slow_every={args.slow_every}: done {done} in {elapsed:.1f}s "
            f"({done / elapsed:.1f}/s), left {left}, ran twice {twice}"
        )
    finally:
        conn = await asyncpg.connect(dsn)
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
