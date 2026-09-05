"""Process-local push notifications; durable runs remain the source of truth."""

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Callable
from typing import Any


class SuggestionEvents:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.on_input: Callable[[uuid.UUID, uuid.UUID, int], None] | None = None
        self.listeners: dict[uuid.UUID, set[asyncio.Queue[dict[str, Any]]]] = (
            defaultdict(set)
        )

    def queued(
        self, conversation_id: uuid.UUID, run_id: uuid.UUID, generation: int
    ) -> None:
        if self.loop and self.on_input:
            self.loop.call_soon_threadsafe(
                self.on_input, conversation_id, run_id, generation
            )

    def subscribe(self, conversation_id: uuid.UUID) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)
        self.listeners[conversation_id].add(queue)
        return queue

    def unsubscribe(
        self, conversation_id: uuid.UUID, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        self.listeners[conversation_id].discard(queue)
        if not self.listeners[conversation_id]:
            del self.listeners[conversation_id]

    def publish(self, conversation_id: uuid.UUID, snapshot: dict[str, Any]) -> None:
        # A slow screen needs current state, not an unbounded event history.
        for queue in self.listeners.get(conversation_id, ()):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(snapshot)


events = SuggestionEvents()
