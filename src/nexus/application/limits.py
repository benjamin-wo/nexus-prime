"""Per-user rate limits for the work that costs money or CPU: messages that reach
the model, and statement imports. Sliding windows, kept in memory: the app runs
as one process, and a restart forgiving the counts is fine for this purpose."""

from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta

from nexus.application.clock import utcnow

type Window = tuple[int, timedelta]  # at most this many in this long

# Generous for a person, tight for a script or a stuck client.
MESSAGES: Sequence[Window] = ((20, timedelta(minutes=1)), (400, timedelta(days=1)))
IMPORTS: Sequence[Window] = ((30, timedelta(minutes=10)),)
DEFAULT_RULES: Mapping[str, Sequence[Window]] = {"message": MESSAGES, "import": IMPORTS}


class RateLimiter:
    def __init__(
        self,
        rules: Mapping[str, Sequence[Window]] = DEFAULT_RULES,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._rules = rules
        self._clock = clock
        self._seen: defaultdict[tuple[str, str], deque[datetime]] = defaultdict(deque)

    def allow(self, kind: str, key: object) -> bool:
        """Count one use of ``kind`` by ``key`` if every window has room; else refuse
        without counting it."""
        windows = self._rules.get(kind)
        if not windows:
            return True
        now = self._clock()
        seen = self._seen[(kind, str(key))]
        longest = max(span for _, span in windows)
        while seen and now - seen[0] >= longest:
            seen.popleft()
        for limit, span in windows:
            if sum(1 for at in seen if now - at < span) >= limit:
                return False
        seen.append(now)
        return True
