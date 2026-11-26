"""The tool types: context, arguments, results and the spec that ties them together."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, ValidationError

from nexus.application.departments import Departments
from nexus.application.fx import RateSource
from nexus.application.ideas import IdeaFinder
from nexus.application.live_prices import PriceLooker
from nexus.application.places import Places
from nexus.application.ports import UnitOfWork
from nexus.application.routes import Routes
from nexus.application.web_lookup import WebLooker
from nexus.application.whereabouts import ZoneFinder
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    User,
)

type UowFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class ToolContext:
    user: User
    uow: UowFactory
    now: datetime
    rates: RateSource | None = None  # for home-currency figures; None converts nothing
    # Makes a one-time Connect Gmail link; None when email isn't set up.
    connect_link: Callable[[User], Awaitable[str]] | None = None
    # The user's own forwarding address, made on first use; None when not set up.
    forward_address: Callable[[User], Awaitable[str]] | None = None
    # The departments, for tools that start a department's run (a research plan).
    departments: Departments | None = None
    # Google Maps places for trips; None when not set up.
    places: Places | None = None
    # Travel times between places, for fitting a new plan into a day; None when not set up.
    routes: Routes | None = None
    # Quick ideas for a trip from the web; None when not set up.
    ideas: IdeaFinder | None = None
    # Looking things up on the web; None when not set up.
    lookup: WebLooker | None = None
    # Live fares, product prices and flight status (SerpApi); None when not set up.
    prices: PriceLooker | None = None
    # Finds the time zone of a place by name, for set_timezone; None when not set up.
    zones: ZoneFinder | None = None
    # Shared by everything the tools change in one chat turn, so Undo reverses it together.
    # None outside a turn: each change then stands alone.
    batch: UUID | None = None
    # What the user said lately (their last few messages), for a tool that must not act on
    # pain or injury. Empty outside a chat turn.
    message: str = ""

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.user.timezone)

    def today(self) -> date:
        return self.now.astimezone(self.tz).date()


NEW_PERSON = "True only when the user said this is a different, new person"


class Args(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


@dataclass(frozen=True, slots=True)
class ToolResult:
    text: str
    wrote: bool = False
    # Extra reply buttons, rows of (label, data), shown under the agent's answer.
    buttons: list[list[tuple[str, str]]] | None = None
    # For an expected failure (run_tool): its coarse class, like "NotFound". Never the message.
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    args: type[Args]
    run: Callable[[ToolContext, Any], Awaitable[ToolResult]]
    # When set, the call needs the user's confirmation; returns what to show them (or
    # nothing, for a call that only reads).
    confirm: Callable[[ToolContext, Any], Awaitable[str]] | None = None
    # Internal tools are created by the kernel only; the model never sees them.
    exposed: bool = True

    def schema(self) -> dict[str, Any]:
        params = inline_refs(self.args.model_json_schema())
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": params},
        }

    def ignored(self, raw: dict[str, Any]) -> list[str]:
        """The keys the model sent that the arguments have no field for."""
        return sorted(k for k in raw if k not in self.args.model_fields)

    def parse(self, raw: dict[str, Any]) -> Any:
        try:
            return self.args.model_validate(raw)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
                for e in exc.errors()
            )
            raise InvalidInput(f"invalid arguments for {self.name}: {problems}") from exc


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve $ref/$defs and drop titles: some providers (Gemini) ignore $defs."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: walk(v) for k, v in node.items() if k not in {"$defs", "title"}}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    result: dict[str, Any] = walk(schema)
    return result


class IdArgs(Args):
    transaction_id: str


class NoArgs(Args):
    pass
