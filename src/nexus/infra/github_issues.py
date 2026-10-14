"""GitHub issues as the ops ticket tracker, over the REST API with a token that only
needs Issues read and write on the one repository."""

from collections.abc import Sequence
from typing import Any

import httpx

from nexus.application.ops_tickets import LABEL, Ticket

API = "https://api.github.com"
PAGES = 5


class GitHubIssues:
    def __init__(self, http: httpx.AsyncClient, repo: str, token: str) -> None:
        self._http = http
        self._base = f"{API}/repos/{repo}/issues"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _call(self, method: str, url: str, **kw: Any) -> Any:
        response = await self._http.request(method, url, headers=self._headers, **kw)
        response.raise_for_status()
        return response.json() if response.content else None

    async def tickets(self) -> list[Ticket]:
        found: list[Ticket] = []
        for page in range(1, PAGES + 1):
            items = await self._call(
                "GET",
                self._base,
                params={"labels": LABEL, "state": "all", "per_page": 100, "page": page},
            )
            for item in items:
                if "pull_request" in item:
                    continue
                found.append(
                    Ticket(
                        number=int(item["number"]),
                        title=str(item.get("title") or ""),
                        body=str(item.get("body") or ""),
                        open=item.get("state") == "open",
                        not_planned=item.get("state_reason") == "not_planned",
                    )
                )
            if len(items) < 100:
                break
        return found

    async def open_ticket(self, title: str, body: str, labels: Sequence[str]) -> int:
        made = await self._call(
            "POST", self._base, json={"title": title, "body": body, "labels": list(labels)}
        )
        return int(made["number"])

    async def edit(
        self,
        number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        labels: Sequence[str] | None = None,
        state: str | None = None,
    ) -> None:
        change: dict[str, Any] = {}
        if title is not None:
            change["title"] = title
        if body is not None:
            change["body"] = body
        if labels is not None:
            change["labels"] = list(labels)
        if state is not None:
            change["state"] = state
            if state == "closed":
                change["state_reason"] = "completed"
        if change:
            await self._call("PATCH", f"{self._base}/{number}", json=change)

    async def comment(self, number: int, body: str) -> None:
        await self._call("POST", f"{self._base}/{number}/comments", json={"body": body})
