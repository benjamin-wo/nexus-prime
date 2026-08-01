import os
import logging
from typing import Optional
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
