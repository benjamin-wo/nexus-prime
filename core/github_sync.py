import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"

# Knowledge base: what each known gap tag would enable, and the concrete
# areas that are currently missing. Custom wishlist tags fall back to a
# generic template but still get the full request/expectation context.
GAP_TAG_KNOWLEDGE: Dict[str, Dict[str, Any]] = {
        "calendar": {
        "what_it_enables": "Configure, list, edit and delete calendar events; answer schedule/meeting questions; set reminders around events.",
        "expected": [
            "Calendar integration (Google Calendar / Outlook) with OAuth",
            "Event CRUD tools & availability checks",
            "Schedule-aware reminder chaining",
            "Plugin + manifest + router wiring",
        ],
        "next_steps": [
            "Add a CalendarPlugin alongside the existing EmailPlugin auth pattern",
            "Reuse /auth flow for calendar scopes, store refresh tokens in UserCredential",
            "Define tools (create_event, list_events, update_event, delete_event) and a manifest yaml",
        ],
    },
    "flight_booking": {
        "what_it_enables": "Search flights, compare prices/connections, and (eventually) book tickets.",
        "expected": [
            "Flight search API integration (lookup, price, availability)",
            "Booking engine or hand-off to partner flow",
            "Plugin + manifest + router wiring",
        ],
        "next_steps": [
            "Start read-only: flight search + price alerts before any checkout flow",
            "Add a SearchFlightPlugin with manifest; keep booking behind HITL confirmation",
        ],
    },
    "bank_transfer": {
        "what_it_enables": "Initiate bank transfers, manage payees, and read account balances.",
        "expected": [
            "Bank/provider API integration or Open Banking connector",
            "Strong multi-factor HITL confirmation on every transfer",
            "Plugin + manifest + router wiring",
        ],
        "next_steps": [
            "Scope down to read-only balance/statement first",
            "Design transfer confirmation flow reusing the existing interrupt() HITL pattern",
        ],
    },
    "smart_home": {
        "what_it_enables": "Control lights, thermostats and other smart-home devices by voice.",
        "expected": [
            "Smart-home bridge integration (Matter/HomeKit/Hub)",
            "Device registry + control tools",
            "Plugin + manifest + router wiring",
        ],
        "next_steps": [
            "Start with a device-status (read-only) capability; add writes behind HITL",
        ],
    },
    "email_send": {
        "what_it_enables": "Compose and send emails on the user's behalf.",
        "expected": [
            "SMTP or Graph/API send permission (Mail.Send)",
            "Compose tool + confirmation step before send",
            "Plugin + manifest + router wiring",
        ],
        "next_steps": [
            "Reuse the OAuth credential store; add Mail.Send scope; clamp recipients to the user's own address until verified",
        ],
    },
    "budget": {
        "what_it_enables": "Set monthly budgets by category, track spend against them, and warn on overruns.",
        "expected": [
            "Budget model + rules engine",
            "Category rollup against ExpenseTransaction",
            "Alerting hooks into ambient.py",
        ],
        "next_steps": [
            "Add BudgetPlugin with set_budget/list_budget tools; surface progress on the dashboard summary",
        ],
    },
    "restaurant_booking": {
        "what_it_enables": "Search restaurants, check tables and make reservations.",
        "expected": [
            "Reservation provider integration",
            "HITL confirmation of slot + party size",
        ],
        "next_steps": [
            "Read-only search first (reuse Tavily/web tooling), then a booking provider",
        ],
    },
}


def _tag_knowledge(tag: str) -> Dict[str, Any]:
    key = tag.strip().lstrip("#").lower()
    if key in GAP_TAG_KNOWLEDGE:
        return GAP_TAG_KNOWLEDGE[key]
    return {
        "what_it_enables": f"A '{key}' capability that fulfils this kind of request.",
        "expected": [
            f"Domain tools & API integration for {key}",
            "Plugin + manifest + router wiring",
            "Telegram/Web UI surface if applicable",
        ],
        "next_steps": [
            "Assess the requested scope in the issue comments; propose a mini-spec, then implement a first read-only slice",
        ],
    }


def _missing_area_status(tag: str) -> List[str]:
    """Inspect the repo to see which layers already exist for this capability."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    clean_tag = tag.strip().lstrip("#").lower()

    checks = []
    checks.append(("Manifest (capabilities/manifests/{}.yaml)".format(clean_tag), os.path.exists(os.path.join(root, "capabilities", "manifests", f"{clean_tag}.yaml"))))
    checks.append(("Plugin registered in CAPABILITY_REGISTRY", _plugin_exists(clean_tag)))
    checks.append(
        (
            "Domain tools module (capabilities/{}/tools.py)".format(clean_tag),
            os.path.exists(os.path.join(root, "capabilities", clean_tag, "tools.py")),
        )
    )
    lines = []
    for label, present in checks:
        lines.append(f"- [{'x' if present else ' '}] {label}")
    return lines


def _plugin_exists(tag: str) -> bool:
    try:
        from orchestrator.router import CAPABILITY_REGISTRY, CapabilityPlugin  # noqa: F401
        return tag in CAPABILITY_REGISTRY
    except Exception:
        return False


def _build_capability_gap_body(
    tag: str,
    prompt: str,
    intent_type: str,
    expectation: Optional[str],
    block_reason: Optional[str],
    agent_reply: Optional[str],
    channel: Optional[str],
    occurred_count: int = 1,
) -> str:
    """Compose a detailed, greppable GitHub issue body for a capability gap."""
    knowledge = _tag_knowledge(tag)
    status_checks = _missing_area_status(tag)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    lines: List[str] = [
        "## 🪄 Feature Request / Capability Gap",
        "",
        f"- **Requested Capability**: `#{tag}`",
        f"- **First Requested**: {timestamp} (occurrence #{occurred_count})",
        f"- **Intent Type**: `{intent_type}`",
        f"- **Channel**: `{channel or 'unknown'}`",
        "",
        "### 🎯 What it enables",
        knowledge["what_it_enables"],
        "",
    ]

    lines.append("### 👤 User request (verbatim)")
    lines.append("```")
    lines.append((prompt or "").strip()[:1500])
    lines.append("```")
    lines.append("")

    if expectation:
        lines.append("### ✅ Expected behaviour")
        lines.append(expectation)
        lines.append("")

    lines.append("### 🧩 Areas currently missing")
    lines.extend(f"- {area}" for area in knowledge["expected"])
    lines.append("")
    lines.append("### 🏗️ Current implementation state")
    lines.extend(status_checks)
    lines.append("")

    if block_reason or intent_type == "unsupported_transaction":
        lines.append("### 🚫 Why it was refused / error")
        lines.append(block_reason or "Guardrail classified the request as an unsupported transactional capability and refused it.")
        lines.append("")

    if agent_reply:
        lines.append("### 💬 What the assistant told the user")
        lines.append("> " + (agent_reply or "").strip()[:600].replace("\n", "\n> "))
        lines.append("")

    lines.append("### 🛠️ Suggested next steps")
    lines.extend(f"- {step}" for step in knowledge["next_steps"])
    lines.append("")
    lines.append("---")
    lines.append("*Automatically logged by Nexus Prime telemetry — the request could not be carried out at the time of asking.*")
    return "\n".join(lines)


def _build_gap_comment(
    tag: str,
    prompt: str,
    intent_type: str,
    expectation: Optional[str],
    block_reason: Optional[str],
    agent_reply: Optional[str],
    channel: Optional[str],
    occurred_count: int = 1,
) -> str:
    """Compact per-occurrence comment with the full context of this request."""
    parts = [
        f"### 🔁 Capability Gap Occurrence #{occurred_count}",
        f"- **User request**:",
        "```",
        (prompt or "").strip()[:1200],
        "```",
        f"- **Intent Type**: `{intent_type}`",
        f"- **Channel**: `{channel or 'unknown'}`",
        f"- **Timestamp**: `{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}`",
    ]
    if expectation:
        parts.append(f"- **Expected**: {expectation[:140]}")
    if block_reason:
        parts.append(f"- **Block reason / error**: {block_reason[:200]}")
    if agent_reply:
        parts.append(f"- **Assistant reply to user**: {agent_reply[:200]}")
    return "\n".join(str(p) for p in parts)


async def sync_capability_gap_to_github_issue(
    tag: str,
    prompt: str,
    intent_type: str,
    expectation: Optional[str] = None,
    block_reason: Optional[str] = None,
    agent_reply: Optional[str] = None,
    channel: Optional[str] = None,
) -> Optional[str]:
    """
    Synchronizes a capability demand request with a GitHub Repository's Issues backlog.
    Performs smart comment deduplication if an issue for `tag` already exists.
    Returns the URL of the created or updated issue, or None if GitHub sync is unconfigured or fails.
    """
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO")

    if not token or not repo:
        logger.debug(
            "GITHUB_TOKEN or GITHUB_REPO not set; skipping GitHub issue sync."
        )
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Telegram-Assistant-Bot-Telemetry/2.0",
    }

    clean_tag = tag.strip().lstrip("#").lower()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Search for existing open issues with the label 'capability-gap'
            list_url = (
                f"{GITHUB_API_BASE}/repos/{repo}/issues?labels=capability-gap&state=open"
            )
            response = await client.get(list_url, headers=headers)

            existing_issue_number: Optional[int] = None
            if response.status_code == 200:
                issues = response.json()
                for issue in issues:
                    title = issue.get("title", "").lower()
                    if f"#{clean_tag}" in title or f": {clean_tag}" in title:
                        existing_issue_number = issue.get("number")
                        break

            if existing_issue_number:
                # Add a +1 comment with this occurrence's full context
                occurred = 1
                try:
                    issue_resp = await client.get(
                        f"{GITHUB_API_BASE}/repos/{repo}/issues/{existing_issue_number}",
                        headers=headers,
                    )
                    if issue_resp.status_code == 200:
                        occurred = int(issue_resp.json().get("comments", 0)) + 1
                except Exception:
                    pass
                comment_url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{existing_issue_number}/comments"
                comment_payload = {
                    "body": _build_gap_comment(
                        tag=clean_tag,
                        prompt=prompt,
                        intent_type=intent_type,
                        expectation=expectation,
                        block_reason=block_reason,
                        agent_reply=agent_reply,
                        channel=channel,
                        occurred_count=occurred,
                    )
                }
                res = await client.post(
                    comment_url, json=comment_payload, headers=headers
                )
                if res.status_code in (200, 201):
                    logger.info(
                        f"Updated existing GitHub Issue #{existing_issue_number} for capability gap #{clean_tag}"
                    )
                    return f"https://github.com/{repo}/issues/{existing_issue_number}"
            else:
                # Create a new GitHub Issue with the full detailed body
                create_url = f"{GITHUB_API_BASE}/repos/{repo}/issues"
                issue_payload = {
                    "title": f"[Wishlist] Missing Capability: #{clean_tag}",
                    "body": _build_capability_gap_body(
                        tag=clean_tag,
                        prompt=prompt,
                        intent_type=intent_type,
                        expectation=expectation,
                        block_reason=block_reason,
                        agent_reply=agent_reply,
                        channel=channel,
                        occurred_count=1,
                    ),
                    "labels": ["capability-gap", "enhancement", "wishlist"],
                }
                res = await client.post(
                    create_url, json=issue_payload, headers=headers
                )
                if res.status_code in (200, 201):
                    data = res.json()
                    issue_num = data.get("number")
                    html_url = data.get("html_url")
                    logger.info(
                        f"Created new GitHub Issue #{issue_num} for capability gap #{clean_tag}"
                    )
                    return html_url

    except Exception as e:
        logger.warning(f"Failed to sync capability gap to GitHub Issue: {e}")

    return None


async def sync_production_bug_to_github_issue(
    fingerprint: str,
    title: str,
    severity: str = "P2",
    subsystem: str = "general",
    detection_source: str = "conversation_audit",
    root_cause: Optional[str] = None,
    reproduction_context: Optional[str] = None,
    suggested_fix: Optional[str] = None,
    error_traceback: Optional[str] = None,
    occurrence_count: int = 1,
    extra_labels: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Synchronize an automated production bug or audit failure report to GitHub Issues.
    Performs fingerprint-based deduplication and auto-comments on existing open issues.
    Returns a dict with {"url": str, "number": int} or None if sync is disabled or fails.

    detection_source == "user_reported" (filed via the /file-issue command, see #14)
    renders a distinct issue shape: no fabricated "audit" framing or traceback
    section, a `user-reported` label instead of `audit-detected`, and any
    `extra_labels` (e.g. `human-review-required`) appended so automated triage
    can gate on it until a human clears the label.
    """
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO")

    if not token or not repo:
        logger.debug(
            "GITHUB_TOKEN or GITHUB_REPO not set; skipping production bug GitHub sync."
        )
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "NexusPrime-Production-Auditor/1.0",
    }

    clean_fp = fingerprint.strip().lower()
    user_reported = detection_source == "user_reported"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Query open issues with label 'bug'
            list_url = f"{GITHUB_API_BASE}/repos/{repo}/issues?labels=bug&state=open"
            response = await client.get(list_url, headers=headers)

            existing_issue_number: Optional[int] = None
            if response.status_code == 200:
                issues = response.json()
                for issue in issues:
                    body = issue.get("body", "") or ""
                    issue_title = issue.get("title", "") or ""
                    if f"<!-- fingerprint: {clean_fp} -->" in body or f"[FP:{clean_fp}]" in issue_title:
                        existing_issue_number = issue.get("number")
                        break

            now_iso = datetime.utcnow().isoformat()

            if existing_issue_number:
                # Issue already exists; append recurrence comment
                comment_url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{existing_issue_number}/comments"
                recurrence_label = "User Report Recurrence" if user_reported else "Production Bug Recurrence"
                comment_body_parts = [
                    f"### 🔄 {recurrence_label} (Occurrence #{occurrence_count})",
                    f"- **Timestamp**: `{now_iso}`",
                    f"- **Detection Source**: `{detection_source}`",
                ]
                if reproduction_context:
                    comment_body_parts.append(f"- **Reproduction Context**:\n> {reproduction_context}")
                if error_traceback:
                    comment_body_parts.append(
                        f"\n<details>\n<summary>Traceback / Log</summary>\n\n```\n{error_traceback}\n```\n</details>"
                    )

                comment_payload = {"body": "\n".join(comment_body_parts)}
                res = await client.post(comment_url, json=comment_payload, headers=headers)
                if res.status_code in (200, 201):
                    logger.info(
                        f"Updated existing GitHub Bug Issue #{existing_issue_number} (recurrence #{occurrence_count})"
                    )
                    return {
                        "url": f"https://github.com/{repo}/issues/{existing_issue_number}",
                        "number": existing_issue_number,
                    }
            else:
                # Create a new GitHub Issue
                create_url = f"{GITHUB_API_BASE}/repos/{repo}/issues"
                if user_reported:
                    # A human filed this themselves via /file-issue — no fabricated
                    # traceback or "audit" framing, and no suggested_fix section
                    # (the triage step classifies category/priority, not a fix).
                    body_parts = [
                        f"<!-- fingerprint: {clean_fp} -->",
                        "## 🐛 User-Reported Bug (filed via /file-issue)",
                        "",
                        f"- **Subsystem**: `{subsystem}`",
                        f"- **Priority**: `{severity}`",
                        f"- **Detection Source**: `{detection_source}`",
                        f"- **Fingerprint**: `{clean_fp}`",
                        f"- **Filed At**: `{now_iso}`",
                        "",
                        "### 📝 Reported by the user",
                        reproduction_context or "N/A",
                        "",
                    ]
                    if root_cause:
                        body_parts.extend(["### 🧭 Triage summary", root_cause, ""])
                    body_parts.append(
                        "*Filed via the /file-issue Telegram command and auto-triaged for "
                        "category/priority — gated behind `human-review-required` until a "
                        "person reviews it.*"
                    )
                else:
                    body_parts = [
                        f"<!-- fingerprint: {clean_fp} -->",
                        f"## 🚨 Production Bug Report (Gemini 3.1 Pro Audit)",
                        "",
                        f"- **Subsystem**: `{subsystem}`",
                        f"- **Severity**: `{severity}`",
                        f"- **Detection Source**: `{detection_source}`",
                        f"- **Fingerprint**: `{clean_fp}`",
                        f"- **Detected At**: `{now_iso}`",
                        "",
                        "### 🔍 Root Cause Analysis",
                        root_cause or "Under investigation.",
                        "",
                        "### 🧪 Reproduction Context",
                        reproduction_context or "N/A",
                        "",
                    ]
                    if suggested_fix:
                        body_parts.extend([
                            "### 🛠️ Suggested Fix",
                            f"```python\n{suggested_fix}\n```",
                            "",
                        ])
                    if error_traceback:
                        body_parts.extend([
                            "<details>",
                            "<summary>Traceback / Log Context</summary>",
                            "",
                            f"```\n{error_traceback}\n```",
                            "</details>",
                            "",
                        ])
                    body_parts.append("*Automatically captured and triaged in the background by Gemini 3.1 Pro Audit.*")

                labels = [
                    "bug",
                    "user-reported" if user_reported else "audit-detected",
                    f"severity:{severity.lower()}",
                    f"area:{subsystem.lower()}",
                ]
                for extra in extra_labels or []:
                    if extra not in labels:
                        labels.append(extra)

                issue_payload = {
                    "title": f"[{severity}][{subsystem.capitalize()}] {title}",
                    "body": "\n".join(body_parts),
                    "labels": labels,
                }
                res = await client.post(create_url, json=issue_payload, headers=headers)
                if res.status_code in (200, 201):
                    data = res.json()
                    issue_num = data.get("number")
                    html_url = data.get("html_url")
                    logger.info(f"Created new GitHub Bug Issue #{issue_num} for {clean_fp}")
                    return {
                        "url": html_url or f"https://github.com/{repo}/issues/{issue_num}",
                        "number": issue_num,
                    }

    except Exception as e:
        logger.warning(f"Failed to sync production bug to GitHub Issue: {e}")

    return None

