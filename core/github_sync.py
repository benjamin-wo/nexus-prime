import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime
import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


async def sync_capability_gap_to_github_issue(
    tag: str, prompt: str, intent_type: str
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
                # Add a +1 comment to existing issue
                comment_url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{existing_issue_number}/comments"
                comment_payload = {
                    "body": (
                        f"+1 Capability Demand Request:\n"
                        f"- **Prompt**: \"{prompt}\"\n"
                        f"- **Intent Type**: `{intent_type}`"
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
                # Create a new GitHub Issue
                create_url = f"{GITHUB_API_BASE}/repos/{repo}/issues"
                issue_payload = {
                    "title": f"[Wishlist] Missing Capability: #{clean_tag}",
                    "body": (
                        f"### Missing Capability Demand Log\n\n"
                        f"- **Requested Tag**: `#{clean_tag}`\n"
                        f"- **First Sample Prompt**: \"{prompt}\"\n"
                        f"- **Intent Type**: `{intent_type}`\n\n"
                        f"*Automatically logged by Telegram Assistant Bot v2.0 Telemetry*"
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
) -> Optional[Dict[str, Any]]:
    """
    Synchronize an automated production bug or audit failure report to GitHub Issues.
    Performs fingerprint-based deduplication and auto-comments on existing open issues.
    Returns a dict with {"url": str, "number": int} or None if sync is disabled or fails.
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
                comment_body_parts = [
                    f"### 🔄 Production Bug Recurrence (Occurrence #{occurrence_count})",
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

                issue_payload = {
                    "title": f"[{severity}][{subsystem.capitalize()}] {title}",
                    "body": "\n".join(body_parts),
                    "labels": [
                        "bug",
                        "audit-detected",
                        f"severity:{severity.lower()}",
                        f"area:{subsystem.lower()}",
                    ],
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

