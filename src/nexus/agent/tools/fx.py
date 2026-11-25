"""Exchange rates for the tools, with a stand-in when none are set up."""

from datetime import date

from nexus.agent.tools.core import ToolContext
from nexus.application.fx import Rate, RateSource


class NoRates:
    async def rate(self, base: str, quote: str, on: date) -> Rate | None:
        return None


def rates(ctx: ToolContext) -> RateSource:
    return ctx.rates if ctx.rates is not None else NoRates()
