"""Bound optional telemetry per authenticated user in this single API process."""

import threading
import time
from collections import OrderedDict, deque


class ObservationLimiter:
    def __init__(self, limit: int = 120, window_seconds: float = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self.users: OrderedDict[str, deque[float]] = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, user_id: str) -> bool:
        now = time.monotonic()
        with self.lock:
            # Active user count and each queue are bounded, including test/dev use.
            queue = self.users.setdefault(user_id, deque())
            self.users.move_to_end(user_id)
            while len(self.users) > 4096:
                self.users.popitem(last=False)
            while queue and queue[0] <= now - self.window:
                queue.popleft()
            if len(queue) >= self.limit:
                return False
            queue.append(now)
            return True


limiter = ObservationLimiter()
