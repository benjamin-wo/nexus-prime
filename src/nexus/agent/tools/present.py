"""``present``: Prime puts a view from the catalog on the user's screen (ADR 0005)."""

from typing import Any

from pydantic import Field

from nexus.agent import progress
from nexus.agent.tools.core import Args, ToolContext, ToolResult, ToolSpec
from nexus.agent.views import CATALOG, ViewStatus


def _describe() -> str:
    views = "; ".join(
        f"{s.name.value} ({', '.join(s.params.model_fields) or 'no params'}): {s.description}"
        for s in CATALOG.values()
        if s.status is ViewStatus.LIVE
    )
    return (
        "Put a view of the user's data on their screen as a card under your reply. Read-only: "
        "it never changes anything and carries its own figures, so call the tool that answers "
        "first and quote only what it gave you. Never for a write or for small talk. An "
        "unknown view or bad params come back as an error: fix them. Views: " + views
    )


class PresentArgs(Args):
    view: str = Field(description="A view's name from the list, like finance.month_outlook")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description='What the view is opened with, like {"month": "2026-09"}; never a user id',
    )
    focus: bool = Field(
        True, description="True for the one view that answers; false for supporting ones"
    )


async def _present(ctx: ToolContext, a: PresentArgs) -> ToolResult:
    from nexus.agent import view_data  # it reads the tool modules, which this one is among

    return await view_data.present(ctx, progress.turn_views(), a.view, a.params, a.focus)


SPECS = (ToolSpec("present", _describe(), PresentArgs, _present),)

READ_ONLY: frozenset[str] = frozenset({"present"})
