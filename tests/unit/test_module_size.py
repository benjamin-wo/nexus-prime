"""No source file grows past 800 lines. Split a big file instead of adding to it."""

from pathlib import Path

LIMIT = 800

# Files already over the limit, at their current size. This list may only shrink: lower or
# remove an entry when a file is split.
LARGE_FILES: dict[str, int] = {
    "src/nexus/agent/graph.py": 1229,
    "src/nexus/agent/service.py": 1481,
    "src/nexus/application/email.py": 1439,
    "src/nexus/application/ops_report.py": 884,
    "src/nexus/application/plans.py": 1257,
    "src/nexus/application/ports.py": 1253,
    "src/nexus/application/travel_research.py": 974,
    "src/nexus/application/trips.py": 971,
    "src/nexus/channels/web/investments_api.py": 835,
    "src/nexus/channels/web/travel_api.py": 2427,
    "src/nexus/evals/cases.py": 2806,
    "src/nexus/infra/db/investment_repository.py": 822,
    "src/nexus/infra/db/ledger_repository.py": 1648,
    "src/nexus/infra/db/tables.py": 1619,
    "src/nexus/infra/db/trip_repository.py": 1153,
    "src/nexus/main.py": 873,
    "web/src/pages/TripArrange.tsx": 808,
}

ROOT = Path(__file__).resolve().parents[2]


def _sources() -> list[Path]:
    found = list((ROOT / "src" / "nexus").rglob("*.py"))
    web = ROOT / "web" / "src"
    for pattern in ("*.ts", "*.tsx"):
        for path in web.rglob(pattern):
            rel = path.relative_to(web).as_posix()
            if ".test." in path.name or "test-setup" in path.name or rel.startswith("e2e/"):
                continue
            found.append(path)
    return sorted(found)


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_no_file_over_the_limit() -> None:
    problems = []
    for path in _sources():
        rel = path.relative_to(ROOT).as_posix()
        count = _lines(path)
        allowed = LARGE_FILES.get(rel, LIMIT)
        if count > allowed:
            problems.append(f"{rel}: {count} lines, allowed {allowed}")
    assert not problems, "\n".join(problems)


def test_large_files_entries_are_still_needed() -> None:
    stale = []
    for rel, allowed in LARGE_FILES.items():
        path = ROOT / rel
        if not path.exists() or _lines(path) <= LIMIT:
            stale.append(f"{rel}: remove from LARGE_FILES")
        elif _lines(path) < allowed:
            stale.append(f"{rel}: lower the entry to {_lines(path)}")
    assert not stale, "\n".join(stale)
