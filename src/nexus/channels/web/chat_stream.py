"""A chat turn as a server-sent event stream: what Kaya is doing as it goes, then the replies.

Frames, each ``event: <name>`` and one line of JSON as ``data``:

- ``step``    ``{"label": "Logging the expense", "state": "running" | "done"}``
- ``replies`` the same list ``POST /api/chat`` returns (the last frame of a turn)
- ``error``   ``{"detail": "..."}`` (the last frame, when the turn failed)

Lines starting with ``:`` are comments (the first one opens the stream; later ones keep it
alive through proxies while a slow model call runs); readers skip them.

The turn runs as a task of its own, not inside the response: a browser that goes away
mid-turn (a closed tab, a dropped connection) doesn't cancel it half-way. It runs to its
end and its replies are kept in the chat history like any other turn's. Only an explicit
Stop (``AgentService.request_stop``) ends it early.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi.responses import StreamingResponse

from nexus.agent.progress import Step
from nexus.agent.service import AgentService, Reply
from nexus.domain.errors import NexusError
from nexus.domain.ledger import UserId

log = logging.getLogger(__name__)

# A comment this often while nothing else is sent, so no proxy decides the stream is dead.
KEEPALIVE_SECONDS = 15.0
HEADERS = {
    "Cache-Control": "no-cache",
    # nginx-style proxies: send each frame as it is written.
    "X-Accel-Buffering": "no",
}
UNEXPECTED = "Something went wrong on our side. Please try again."

# Strong references: a task nobody holds can be collected before it finishes.
_turns: set[asyncio.Task[None]] = set()

type Frame = tuple[str, Any]


def frame(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def stream_turn(
    service: AgentService,
    user: UserId,
    message: str,
    ref: str,
    *,
    replies: Callable[[list[Reply]], list[dict[str, Any]]],
) -> StreamingResponse:
    """Run the turn in the background and stream its steps and replies. ``replies`` turns
    the service's replies into the JSON-ready list ``POST /api/chat`` sends."""
    queue: asyncio.Queue[Frame | None] = asyncio.Queue()

    async def on_step(step: Step) -> None:
        queue.put_nowait(("step", {"label": step.label, "state": step.state}))

    async def turn() -> None:
        try:
            done = await service.handle_text(user, message, ref, on_step=on_step)
            queue.put_nowait(("replies", replies(done)))
        except NexusError as exc:
            queue.put_nowait(("error", {"detail": str(exc)}))
        except Exception:
            log.exception("chat turn failed")
            queue.put_nowait(("error", {"detail": UNEXPECTED}))
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(turn())
    _turns.add(task)
    task.add_done_callback(_turns.discard)

    async def frames() -> AsyncIterator[str]:
        yield ": open\n\n"
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), KEEPALIVE_SECONDS)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                return
            yield frame(*item)

    return StreamingResponse(frames(), media_type="text/event-stream", headers=HEADERS)
