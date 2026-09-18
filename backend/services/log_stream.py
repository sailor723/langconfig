"""
Live backend log streaming for the mini-VS-Code bottom panel (Terminal tab).

Attaches a logging.Handler to the root + uvicorn loggers that pushes formatted
log lines into an in-memory ring buffer and broadcasts them to active SSE
subscribers. The debug router serves these over GET /api/debug/logs/stream.
"""
import asyncio
import logging
from collections import deque
from typing import Deque, List, Set

logger = logging.getLogger(__name__)

# Number of recent lines kept in memory so a freshly-opened Terminal tab
# gets history instead of starting empty.
MAX_BUFFER = 500
# Per-subscriber queue bound; slow consumers get dropped lines, never block
# the logging path.
_MAX_QUEUE = 200


class _LogHub:
    """In-memory log ring buffer + subscriber fan-out."""

    def __init__(self) -> None:
        self._buffer: Deque[str] = deque(maxlen=MAX_BUFFER)
        self._subscribers: Set[asyncio.Queue] = set()

    def snapshot(self) -> List[str]:
        return list(self._buffer)

    def publish(self, line: str) -> None:
        self._buffer.append(line)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(line)
            except asyncio.QueueFull:
                # Drop for slow consumers; never block logging itself.
                pass

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)


hub = _LogHub()


class _BroadcastHandler(logging.Handler):
    """logging.Handler that formats records and broadcasts them to the hub."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            hub.publish(self.format(record))
        except Exception:
            self.handleError(record)


_handler = _BroadcastHandler(level=logging.DEBUG)
_handler.setFormatter(logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
))


def attach_log_stream() -> None:
    """Attach the broadcast handler to root + uvicorn loggers (idempotent).

    Root captures app logs; uvicorn's own loggers keep their default handlers
    and set propagate=False, so we attach directly to them as well to also
    surface HTTP access lines in the Terminal tab.
    """
    root = logging.getLogger()
    if _handler in root.handlers:
        return
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addHandler(_handler)
    root.info("Log stream handler attached (bottom-panel Terminal tab)")


def detach_log_stream() -> None:
    """Remove the broadcast handler (tests / shutdown)."""
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).removeHandler(_handler)
