"""Web search in the evals: a canned lookup, so the web_search tool works offline, for
free and the same every time. ``--live-web`` swaps in the real one (see ``live_web``)."""

from datetime import datetime

from nexus.application.web_lookup import Lookup
from nexus.application.web_search import Recency
from nexus.domain.ledger import UserId
from nexus.domain.travel_research import Source
from nexus.evals import seed

# A made-up page on a domain reserved for examples. Replies are checked for these.
DOMAIN = "example.com"
URL = f"https://news.{DOMAIN}/nexus-evals/latest"
TITLE = "Example Daily: the latest"
TEXT = (
    "The Example Daily page covers this and was updated today. It gives the current "
    "figures and says they can change during the day [1]."
)


class CannedLookup:
    """Answers every question the same way, citing one made-up page dated as the eval
    clock's day, and remembers what was asked."""

    def __init__(self, today: datetime = seed.NOW) -> None:
        self._today = today
        self.questions: list[str] = []

    async def ask(
        self,
        user_id: UserId,
        question: str,
        *,
        recent: Recency | None = None,
        local_query: str | None = None,
    ) -> Lookup:
        self.questions.append(question)
        source = Source(1, URL, TITLE, self._today.date(), self._today)
        return Lookup(question, TEXT, [source], read_pages=True)
