"""In-process service metrics (SDD §12). Exposed as JSON at GET /metrics."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import Any


class Metrics:
    def __init__(self) -> None:
        self.counters: defaultdict[str, int] = defaultdict(int)
        self.samples: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=5000))
        self.started = time.time()

    def inc(self, name: str, n: int = 1) -> None:
        self.counters[name] += n

    def observe(self, name: str, seconds: float) -> None:
        self.samples[name].append(seconds)

    @contextmanager
    def timer(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, time.perf_counter() - t0)

    @staticmethod
    def _pct(values: list[float], p: float) -> float | None:
        if not values:
            return None
        s = sorted(values)
        k = min(len(s) - 1, max(0, round(p / 100 * (len(s) - 1))))
        return round(s[k] * 1000, 2)

    def snapshot(self, gauges: dict[str, Any] | None = None) -> dict[str, Any]:
        lat = {}
        for name, dq in self.samples.items():
            vals = list(dq)
            lat[name] = {
                "count": len(vals),
                "p50_ms": self._pct(vals, 50),
                "p95_ms": self._pct(vals, 95),
                "max_ms": self._pct(vals, 100),
            }
        return {
            "uptime_s": round(time.time() - self.started),
            "counters": dict(self.counters),
            "latency": lat,
            "gauges": gauges or {},
        }

    def reset(self) -> None:
        self.counters.clear()
        self.samples.clear()


metrics = Metrics()
