"""Transient, local circuit state for each independent capability and market."""
from threading import Lock
import time


class SourceFailure(RuntimeError):
    def __init__(self, reason: str, *, retry_after: float = 0):
        super().__init__(reason)
        self.retry_after = retry_after


class InvalidRequest(ValueError):
    """Invalid caller parameters should not be retried at another source."""


class NoData(Exception):
    """A successful, authoritative empty result, e.g. a confirmed closed session."""


class Cooldown:
    def __init__(self, *, clock=None):
        self.clock = clock or time.monotonic
        self.states = {}
        self.lock = Lock()

    def available(self, key):
        with self.lock:
            return self.clock() >= self.states.get(key, (0, 0))[1]

    def failed(self, key, delay=0):
        with self.lock:
            count, until = self.states.get(key, (0, 0))
            count += 1
            window = max(min(delay, 600), 30 if count >= 3 else 0)
            self.states[key] = (count, max(until, self.clock() + window))

    def succeeded(self, key):
        with self.lock:
            self.states.pop(key, None)
