"""The ops report: what went wrong or slow in a window, grouped into problems a
developer (or a ticket bot) can act on.

Each problem has a stable id, the same every time the same thing goes wrong, so a
ticket can be opened once, updated while it keeps happening and closed when it
stops. A problem says how bad, where in the code when known, how often, how many
users it touched (counted by hash), a few traces to find its log lines, and a hint.
Everything in it comes from ops events and the jobs table: names, timings, status
codes and error types, never anything a user said, wrote or spent.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Literal

from nexus.application.ops import fingerprint

Severity = Literal["high", "medium", "low"]
RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}

SLOW_TURN_MS = 30_000
TURN_P90_MS = 15_000
SAMPLE_TRACES = 3


@dataclass(frozen=True, slots=True)
class Problem:
    id: str
    severity: Severity
    area: str
    title: str
    count: int
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    where: str | None = None
    users: int | None = None
    traces: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class Checks:
    """What the report reads besides events."""

    now: datetime
    since: datetime
    schedules: Sequence[tuple[str, timedelta]] = ()  # recurring jobs, when jobs run
    stuck_jobs: list[dict[str, Any]] = field(default_factory=list)
    overdue_jobs: list[dict[str, Any]] = field(default_factory=list)
    failed_jobs: list[dict[str, Any]] = field(default_factory=list)
    last_done: dict[str, datetime] = field(default_factory=dict)
    webhook: dict[str, Any] | None = None  # Telegram's getWebhookInfo
    openrouter: dict[str, Any] | None = None  # OpenRouter's key status
    broken_mailboxes: int = 0
    search_credits: dict[str, int] = field(default_factory=dict)
    search_monthly: int | None = None
    database_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class Report:
    since: datetime
    until: datetime
    summary: dict[str, Any]
    problems: list[Problem]

    def as_json(self) -> dict[str, Any]:
        return {
            "since": self.since.isoformat(),
            "until": self.until.isoformat(),
            "summary": self.summary,
            "problems": [_problem_json(p) for p in self.problems],
        }


def _problem_json(problem: Problem) -> dict[str, Any]:
    found = asdict(problem)
    for key in ("first_seen", "last_seen"):
        if found[key] is not None:
            found[key] = found[key].isoformat()
    return found


def _p(values: Sequence[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _span(rows: Iterable[dict[str, Any]]) -> tuple[datetime | None, datetime | None]:
    times = [r["at"] for r in rows]
    return (min(times), max(times)) if times else (None, None)


def _traces(rows: Sequence[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for r in reversed(rows):
        if r.get("trace") and r["trace"] not in seen:
            seen.append(r["trace"])
        if len(seen) == SAMPLE_TRACES:
            break
    return seen


def _users(rows: Iterable[dict[str, Any]]) -> int:
    return len({r["user_ref"] for r in rows if r.get("user_ref")})


def _problem(
    key: Sequence[object],
    severity: Severity,
    area: str,
    title: str,
    rows: Sequence[dict[str, Any]],
    **extra: Any,
) -> Problem:
    first, last = _span(rows)
    return Problem(
        id=fingerprint(*key),
        severity=severity,
        area=area,
        title=title,
        count=extra.pop("count", len(rows)),
        first_seen=first,
        last_seen=last,
        users=_users(rows) or None,
        traces=_traces(rows),
        **extra,
    )


def build(
    events: Sequence[dict[str, Any]],
    requests: Sequence[dict[str, Any]],
    calls: Sequence[dict[str, Any]],
    checks: Checks,
) -> Report:
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        by_kind[e["kind"]].append(e)
    # An error logged during a failed turn, tool or job is that failure, not another
    # problem: it lends the failure where in the code it happened.
    failed = {
        e["trace"]
        for e in (*by_kind["turn"], *by_kind["tool"], *by_kind["job"])
        if e.get("trace") and not e["ok"] and (e["kind"] != "tool" or e["detail"].get("crashed"))
    }
    explained = [e for e in by_kind["log"] if e.get("trace") in failed]
    wheres: dict[str, Counter[str]] = defaultdict(Counter)
    for e in explained:
        if e["detail"].get("where") and e["detail"].get("error"):
            wheres[e["trace"]][e["detail"]["where"]] += 1
    loose = [e for e in by_kind["log"] if e.get("trace") not in failed]
    problems = [
        *_from_logs(loose),
        *_from_turns(by_kind["turn"], wheres),
        *_from_models(by_kind["model"], by_kind["turn"]),
        *_from_tools(by_kind["tool"], wheres),
        *_from_jobs(by_kind["job"], checks, wheres),
        *_from_requests(requests),
        *_from_calls(calls),
        *_from_checks(checks),
    ]
    problems.sort(key=lambda p: (RANK[p.severity], -p.count, p.title))
    return Report(checks.since, checks.now, _summary(by_kind, requests, calls, checks), problems)


# --- Problems ---------------------------------------------------------------------

# Log lines that other parts of the report already cover.
_COVERED = (("nexus.agent.service", "turn took"),)


def _from_logs(rows: list[dict[str, Any]]) -> Iterable[Problem]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        d = r["detail"]
        if any(r["name"] == lg and d.get("template", "").startswith(t) for lg, t in _COVERED):
            continue
        groups[d.get("fp") or fingerprint(r["name"], d.get("template"))].append(r)
    for fp, group in groups.items():
        d = group[-1]["detail"]
        levels = Counter(g["detail"].get("level") for g in group)
        errors = Counter(g["detail"].get("error") for g in group if g["detail"].get("error"))
        places = Counter(g["detail"].get("where") for g in group if g["detail"].get("where"))
        severity: Severity
        if levels.get("error") or levels.get("critical"):
            severity = "high"
        elif errors or len(group) >= 5:
            severity = "medium"
        else:
            severity = "low"
        yield _problem(
            ("log", fp),
            severity,
            "code",
            f"{group[-1]['name']}: {d.get('template', '?')}",
            group,
            where=places.most_common(1)[0][0] if places else None,
            detail={"levels": dict(levels), "errors": dict(errors)},
            hint="Logged as a warning or error. The traces find the full lines in the logs.",
        )


def _where(rows: Sequence[dict[str, Any]], wheres: dict[str, Counter[str]]) -> str | None:
    found: Counter[str] = Counter()
    for r in rows:
        found.update(wheres.get(r.get("trace") or "", {}))
    return found.most_common(1)[0][0] if found else None


def _from_turns(turns: list[dict[str, Any]], wheres: dict[str, Counter[str]]) -> Iterable[Problem]:
    failed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in turns:
        if not t["ok"]:
            failed[t["detail"].get("error", "error")].append(t)
    for error, group in failed.items():
        yield _problem(
            ("turn-failed", error),
            "high",
            "chat",
            f"Chat turns failed with {error}",
            group,
            where=_where(group, wheres),
            hint="The user got the 'something went wrong' reply. The traces find the error.",
        )
    slow = [t for t in turns if t["ok"] and (t["ms"] or 0) >= SLOW_TURN_MS]
    if slow:
        tools: Counter[str] = Counter()
        for t in slow:
            tools.update(t["detail"].get("tools") or {})
        model_share = [
            t["detail"].get("model_ms", 0) / t["ms"] for t in slow if t["ms"] and t["ms"] > 0
        ]
        yield _problem(
            ("slow-turns",),
            "medium",
            "chat",
            f"{len(slow)} chat {'reply' if len(slow) == 1 else 'replies'} took over "
            f"{SLOW_TURN_MS // 1000}s",
            slow,
            detail={
                "slowest_ms": max(t["ms"] for t in slow),
                "model_share": round(median(model_share), 2) if model_share else None,
                "model_calls": max(t["detail"].get("model_calls", 0) for t in slow),
                "tools": dict(tools.most_common(8)),
                "fallback": sum(1 for t in slow if t["detail"].get("fallback")),
            },
            hint=(
                "model_share is the median share of the time spent waiting on the model; "
                "the rest is tools, the database and building the prompt. Many tool calls "
                "in one turn point to a missing bulk tool."
            ),
        )
    times = [t["ms"] for t in turns if t["ok"] and t["ms"] is not None]
    p90 = _p(times, 0.9)
    if p90 is not None and len(times) >= 10 and p90 >= TURN_P90_MS:
        yield _problem(
            ("turn-p90",),
            "low",
            "chat",
            f"One chat reply in ten takes over {p90 // 1000}s",
            turns,
            count=len(times),
            detail={"p90_ms": p90, "median_ms": int(median(times))},
        )


def _from_models(models: list[dict[str, Any]], turns: list[dict[str, Any]]) -> Iterable[Problem]:
    failed: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for m in models:
        if not m["ok"]:
            failed[(m["name"], m["detail"].get("error", "error"))].append(m)
    calls = Counter(m["name"] for m in models)
    for (model, error), group in failed.items():
        share = len(group) / max(1, calls[model])
        yield _problem(
            ("model-error", model, error),
            "high" if share >= 0.2 and len(group) >= 3 else "medium",
            "models",
            f"{model} failed with {error}",
            group,
            detail={"share_of_calls": round(share, 2)},
            hint="The fallback model answers when it can; see whether this model or its "
            "provider is having trouble.",
        )
    fell_back = [t for t in turns if t["detail"].get("fallback")]
    if len(fell_back) >= 3 and len(fell_back) / max(1, len(turns)) >= 0.1:
        yield _problem(
            ("fallback-rate",),
            "medium",
            "models",
            f"The fallback model answered {len(fell_back)} of {len(turns)} chat turns",
            fell_back,
            hint="The chat model is failing often; see the model errors.",
        )


def _from_tools(tools: list[dict[str, Any]], wheres: dict[str, Counter[str]]) -> Iterable[Problem]:
    crashed: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    refused: dict[str, list[dict[str, Any]]] = defaultdict(list)
    calls = Counter(t["name"] for t in tools)
    for t in tools:
        if t["detail"].get("crashed"):
            crashed[(t["name"], t["detail"].get("error", "error"))].append(t)
        elif not t["ok"]:
            refused[t["name"]].append(t)
    for (tool, error), group in crashed.items():
        yield _problem(
            ("tool-crash", tool, error),
            "high",
            "tools",
            f"Tool {tool} crashed with {error}",
            group,
            where=_where(group, wheres),
            hint="The model was told something went wrong. The traces find the error's "
            "log line, with where it happened.",
        )
    for tool, group in refused.items():
        share = len(group) / max(1, calls[tool])
        if len(group) >= 5 and share >= 0.3:
            yield _problem(
                ("tool-refused", tool),
                "low",
                "tools",
                f"Tool {tool} refused {len(group)} of {calls[tool]} calls",
                group,
                detail={"share_of_calls": round(share, 2)},
                hint="The model keeps calling it wrongly: its description or arguments "
                "may need to be clearer.",
            )


def _from_jobs(
    jobs: list[dict[str, Any]], checks: Checks, wheres: dict[str, Counter[str]]
) -> Iterable[Problem]:
    failed: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for j in jobs:
        if not j["ok"]:
            failed[(j["name"], j["detail"].get("error", "error"))].append(j)
    for (kind, error), group in failed.items():
        final = [g for g in group if g["detail"].get("final")]
        if not final and len(group) < 3:
            continue  # a retry that may yet succeed
        yield _problem(
            ("job-failed", kind, error),
            "high" if final else "medium",
            "jobs",
            f"Job {kind} {'gave up' if final else 'keeps failing'} with {error}",
            group,
            where=_where(group, wheres),
            detail={"gave_up": len(final), "attempts": len(group)},
            hint="The jobs table's last_error has the message; the traces find the lines.",
        )
    for row in checks.stuck_jobs:
        yield Problem(
            id=fingerprint("job-stuck", row["kind"]),
            severity="high",
            area="jobs",
            title=f"Job {row['kind']} is stuck running past its lease",
            count=1,
            detail={"attempts": row.get("attempts")},
            hint="Its worker died mid-run, or it hangs; it's claimed again once the lease ends.",
        )
    for row in checks.overdue_jobs:
        yield Problem(
            id=fingerprint("job-overdue", row["kind"]),
            severity="high",
            area="jobs",
            title=f"{row['count']} {row['kind']} job(s) waiting well past their time",
            count=int(row["count"]),
            first_seen=row.get("oldest"),
            hint="The job runner isn't keeping up, or isn't running.",
        )
    for kind, every in checks.schedules:
        last = checks.last_done.get(kind)
        late = max(every * 3, timedelta(hours=2))
        if last is None or checks.now - last > late:
            yield Problem(
                id=fingerprint("job-not-running", kind),
                severity="high",
                area="jobs",
                title=f"Scheduled job {kind} hasn't finished "
                + ("yet" if last is None else f"since {last:%d %b %H:%M} UTC"),
                count=1,
                last_seen=last,
                detail={"every_minutes": int(every.total_seconds() // 60)},
                hint="See whether it's failing (its own problem) or not being scheduled.",
            )


def _from_requests(requests: Sequence[dict[str, Any]]) -> Iterable[Problem]:
    for r in requests:
        if r["failures"]:
            yield Problem(
                id=fingerprint("request-5xx", r["name"]),
                severity="high",
                area="web",
                title=f"{r['name']} failed {r['failures']} of {r['calls']} times",
                count=int(r["failures"]),
                detail={"calls": int(r["calls"])},
                hint="A server error reached the web app or Telegram.",
            )


def _from_calls(calls: Sequence[dict[str, Any]]) -> Iterable[Problem]:
    for c in calls:
        failures, total = int(c["failures"]), int(c["calls"])
        if failures < 3 or failures / max(1, total) < 0.1:
            continue
        share = failures / total
        yield Problem(
            id=fingerprint("outside-errors", c["name"]),
            severity="high" if share >= 0.5 else "medium",
            area="outside",
            title=f"Calls to {c['name']} failed {failures} of {total} times",
            count=failures,
            detail={
                "errors": sorted(e for e in (c.get("errors") or []) if e),
                "p90_ms": int(c["p90_ms"]) if c.get("p90_ms") is not None else None,
            },
            hint="Timeouts and 5xx are the service's side; 401/403 a key; 429 a rate limit.",
        )


def _from_checks(checks: Checks) -> Iterable[Problem]:
    hook = checks.webhook or {}
    pending = int(hook.get("pending_update_count") or 0)
    if pending >= 10:
        yield Problem(
            id=fingerprint("webhook-backlog"),
            severity="high",
            area="telegram",
            title=f"{pending} Telegram updates are waiting to be delivered",
            count=pending,
            hint="Telegram can't reach the webhook or it answers slowly.",
        )
    last_error = hook.get("last_error_date")
    if last_error and datetime.fromtimestamp(int(last_error), checks.now.tzinfo) >= checks.since:
        yield Problem(
            id=fingerprint("webhook-error", hook.get("last_error_message", "")[:60]),
            severity="medium",
            area="telegram",
            title=f"Telegram couldn't deliver an update: {hook.get('last_error_message', '?')}",
            count=1,
            last_seen=datetime.fromtimestamp(int(last_error), checks.now.tzinfo),
        )
    remaining = (checks.openrouter or {}).get("limit_remaining")
    if isinstance(remaining, int | float) and remaining < 5:
        yield Problem(
            id=fingerprint("openrouter-credit"),
            severity="high" if remaining < 1 else "medium",
            area="credits",
            title=f"OpenRouter credit is low: ${remaining:.2f} left",
            count=1,
            hint="Every model call fails once it runs out.",
        )
    if checks.broken_mailboxes:
        yield Problem(
            id=fingerprint("mailbox-broken"),
            severity="medium",
            area="email",
            title=f"{checks.broken_mailboxes} connected mailbox(es) stopped working",
            count=checks.broken_mailboxes,
            hint="Usually an expired or revoked Gmail grant: the user reconnects on the "
            "Email page.",
        )
    used = sum(checks.search_credits.values())
    if checks.search_monthly and used >= 0.9 * checks.search_monthly:
        yield Problem(
            id=fingerprint("search-credits"),
            severity="medium",
            area="credits",
            title=f"Web search used {used} of {checks.search_monthly} credits this month",
            count=used,
            detail={"by_product": checks.search_credits},
            hint="Searches fall back to OpenRouter's web plugin (paid) when they run out.",
        )


# --- Summary ----------------------------------------------------------------------


def _summary(
    by_kind: dict[str, list[dict[str, Any]]],
    requests: Sequence[dict[str, Any]],
    calls: Sequence[dict[str, Any]],
    checks: Checks,
) -> dict[str, Any]:
    turns = by_kind["turn"]
    times = [t["ms"] for t in turns if t["ok"] and t["ms"] is not None]
    models = by_kind["model"]
    tools = by_kind["tool"]
    jobs = by_kind["job"]
    users = {e["user_ref"] for e in turns if e.get("user_ref")}
    return {
        "turns": {
            "count": len(turns),
            "failed": sum(not t["ok"] for t in turns),
            "median_ms": int(median(times)) if times else None,
            "p90_ms": _p(times, 0.9),
            "max_ms": max(times) if times else None,
            "fallback": sum(1 for t in turns if t["detail"].get("fallback")),
            "users": len(users),
        },
        "models": {
            name: {
                "calls": n,
                "failed": sum(1 for m in models if m["name"] == name and not m["ok"]),
            }
            for name, n in Counter(m["name"] for m in models).most_common()
        },
        "tools": {
            "calls": len(tools),
            "crashed": sum(1 for t in tools if t["detail"].get("crashed")),
            "refused": sum(1 for t in tools if not t["ok"] and not t["detail"].get("crashed")),
        },
        "jobs": {"runs": len(jobs), "failed": sum(not j["ok"] for j in jobs)},
        "requests": {
            "calls": sum(int(r["calls"]) for r in requests),
            "failed": sum(int(r["failures"]) for r in requests),
        },
        "outside": {
            c["name"]: {"calls": int(c["calls"]), "failed": int(c["failures"])} for c in calls
        },
        "warnings": len(by_kind["log"]),
        "database_mb": round(checks.database_bytes / 1e6, 1) if checks.database_bytes else None,
        "openrouter_remaining": (checks.openrouter or {}).get("limit_remaining"),
        "search_credits": checks.search_credits or None,
    }


# --- Markdown ---------------------------------------------------------------------

_MARK = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def markdown(report: Report) -> str:
    s = report.summary
    t = s["turns"]
    lines = [
        f"# Nexus ops report, {report.since:%d %b %H:%M} to {report.until:%d %b %H:%M} UTC",
        "",
        f"- Chat: {t['count']} turns from {t['users']} users, {t['failed']} failed, "
        f"median {_secs(t['median_ms'])}, p90 {_secs(t['p90_ms'])}, slowest "
        f"{_secs(t['max_ms'])}, fallback {t['fallback']}",
        f"- Tools: {s['tools']['calls']} calls, {s['tools']['crashed']} crashed, "
        f"{s['tools']['refused']} refused",
        f"- Jobs: {s['jobs']['runs']} runs, {s['jobs']['failed']} failed",
        f"- Requests: {s['requests']['calls']}, {s['requests']['failed']} server errors",
        f"- Warnings and errors logged: {s['warnings']}",
    ]
    if s["database_mb"] is not None:
        lines.append(f"- Database: {s['database_mb']} MB")
    if s["openrouter_remaining"] is not None:
        lines.append(f"- OpenRouter credit left: ${s['openrouter_remaining']:.2f}")
    lines += ["", f"## Problems ({len(report.problems)})", ""]
    if not report.problems:
        lines.append("None.")
    for p in report.problems:
        lines.append(f"### {_MARK[p.severity]} {p.title}")
        facts = [f"id `{p.id}`", p.area, f"{p.count} times"]
        if p.users:
            facts.append(f"{p.users} user(s)")
        if p.last_seen:
            facts.append(f"last {p.last_seen:%d %b %H:%M}")
        lines.append(" · ".join(facts))
        if p.where:
            lines.append(f"- Where: `{p.where}`")
        if p.detail:
            shown = ", ".join(f"{k}: {v}" for k, v in p.detail.items() if v not in (None, {}, 0))
            if shown:
                lines.append(f"- Detail: {shown}")
        if p.traces:
            lines.append(f"- Traces: {', '.join(f'`{x}`' for x in p.traces)}")
        if p.hint:
            lines.append(f"- {p.hint}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _secs(ms: int | None) -> str:
    return "n/a" if ms is None else f"{ms / 1000:.1f}s"
