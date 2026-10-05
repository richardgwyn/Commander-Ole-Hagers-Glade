"""Connection and message-rate limits."""

import time


class TokenBucket:
    def __init__(self, rate=20.0, burst=40.0):
        self.rate = rate
        self.capacity = burst
        self.tokens = burst
        self.updated = time.monotonic()

    def consume(self, amount=1.0):
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens < amount:
            return False
        self.tokens -= amount
        return True
