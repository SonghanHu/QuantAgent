"""Thread-safe event bus for real-time agent progress updates."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import json
import math
from queue import Queue
from threading import Lock
from typing import Any

Event = dict[str, Any]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventBus:
    """Simple pub/sub bus with in-memory event history for replay."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._history: list[Event] = []
        self._subscribers: dict[int, Queue[Event]] = {}
        self._next_subscriber_id = 1

    def emit(self, event_type: str, **payload: Any) -> Event:
        event: Event = _json_safe({"type": event_type, "ts": utc_now_iso(), **payload})
        with self._lock:
            self._history.append(event)
            queues = list(self._subscribers.values())
        for q in queues:
            q.put(event)
        return event

    def subscribe(self, *, replay: bool = True) -> tuple[int, Queue[Event], list[Event]]:
        queue: Queue[Event] = Queue()
        with self._lock:
            subscriber_id = self._next_subscriber_id
            self._next_subscriber_id += 1
            self._subscribers[subscriber_id] = queue
            history = list(self._history) if replay else []
        return subscriber_id, queue, history

    def unsubscribe(self, subscriber_id: int) -> None:
        with self._lock:
            self._subscribers.pop(subscriber_id, None)

    def history(self) -> list[Event]:
        with self._lock:
            return list(self._history)

    def extend(self, events: Iterable[Event]) -> None:
        for event in events:
            self.emit(event.get("type", "unknown"), **{k: v for k, v in event.items() if k not in {"type", "ts"}})


def _sanitize_for_json(value: Any) -> Any:
    """Recursively replace NaN/Inf and odd scalars so Starlette/FastAPI WebSocket JSON is valid."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, dict):
        return {str(k): _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_json(v) for v in value]
    item_fn = getattr(value, "item", None)
    if callable(item_fn):
        try:
            return _sanitize_for_json(item_fn())
        except Exception:
            return str(value)
    return str(value)


def _json_safe(value: Any) -> Any:
    try:
        cleaned = _sanitize_for_json(value)
        # Match browser/Starlette strict JSON (no NaN)
        return json.loads(json.dumps(cleaned, default=str, allow_nan=False))
    except (TypeError, ValueError):
        return str(value)


def sanitize_for_json(value: Any) -> Any:
    """Public helper for payloads that must pass strict JSON (e.g. WebSocket)."""
    return _sanitize_for_json(value)


__all__ = ["Event", "EventBus", "utc_now_iso", "sanitize_for_json"]
