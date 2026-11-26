"""Tools the agent can call. Each is a thin wrapper over one use case.

Tools never take a user id: the acting user comes from the authenticated
channel via ToolContext. Arguments the model sends that a tool doesn't
declare, including any attempt at ``user_id``, are dropped.

The package is split by area (see registry.py for the order the model sees them in);
this module re-exports what the rest of the code imports.
"""

from nexus.agent.tools.core import ToolContext, ToolResult, ToolSpec, UowFactory
from nexus.agent.tools.email import AnswerEmailArgs
from nexus.agent.tools.food import LogFoodArgs
from nexus.agent.tools.health import HEALTH_OFF
from nexus.agent.tools.helpers import parse_money
from nexus.agent.tools.registry import (
    MENU_OF,
    READ_ONLY,
    args_json,
    build_tools,
    run_tool,
    safe_for_images,
)
from nexus.agent.tools.trips.search import FlightPricesArgs

__all__ = [
    "HEALTH_OFF",
    "MENU_OF",
    "READ_ONLY",
    "AnswerEmailArgs",
    "FlightPricesArgs",
    "LogFoodArgs",
    "ToolContext",
    "ToolResult",
    "ToolSpec",
    "UowFactory",
    "args_json",
    "build_tools",
    "parse_money",
    "run_tool",
    "safe_for_images",
]
