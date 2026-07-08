"""Observability: correlation IDs + pipeline stats.

- correlation_id lives in a contextvar, so every log line in a request's async
  journey (including BackgroundTasks) is tagged automatically — no parameter
  threading through the call stack.
- StatsTracker is an in-memory aggregate. Its counters map 1:1 onto Prometheus
  metrics (Counter/Histogram) if this ever needs real scraping — the swap is
  contained to this file.
"""
import contextvars
import logging
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")


def new_correlation_id() -> str:
    cid = uuid.uuid4().hex[:8]
    correlation_id.set(cid)
    return cid


class CorrelationFilter(logging.Filter):
    """Injects the current correlation id into every log record as %(cid)s."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.cid = correlation_id.get()
        return True


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationFilter())
    handler.setFormatter(logging.Formatter(
        '{"ts":"%(asctime)s","level":"%(levelname)s","cid":"%(cid)s",'
        '"logger":"%(name)s","msg":"%(message)s"}'
    ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


class StageTimer:
    """Times named pipeline stages: with timer.stage('triage'): ..."""

    def __init__(self) -> None:
        self.timings_ms: dict[str, float] = {}

    def stage(self, name: str):
        timer = self

        class _Ctx:
            def __enter__(self):
                self._t0 = time.perf_counter()

            def __exit__(self, *exc):
                timer.timings_ms[name] = round((time.perf_counter() - self._t0) * 1000, 1)

        return _Ctx()


@dataclass
class StatsTracker:
    total: int = 0
    auto_routed: int = 0
    fallbacks: int = 0
    errors: int = 0
    confidence_sum: float = 0.0
    by_group: Counter = field(default_factory=Counter)
    by_priority: Counter = field(default_factory=Counter)
    stage_ms_sum: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def record(self, decision, timings_ms: dict[str, float]) -> None:
        self.total += 1
        self.auto_routed += int(decision.auto_routed)
        self.fallbacks += int(not decision.auto_routed)
        self.confidence_sum += decision.triage.confidence
        self.by_group[decision.routed_to] += 1
        self.by_priority[f"P{decision.triage.priority.value}"] += 1
        for stage, ms in timings_ms.items():
            self.stage_ms_sum[stage] += ms

    def record_error(self) -> None:
        self.errors += 1

    def snapshot(self) -> dict:
        n = max(self.total, 1)
        return {
            "processed": self.total,
            "auto_routed": self.auto_routed,
            "auto_route_rate": round(self.auto_routed / n, 3),
            "low_confidence_fallbacks": self.fallbacks,
            "errors": self.errors,
            "avg_confidence": round(self.confidence_sum / n, 3),
            "by_group": dict(self.by_group),
            "by_priority": dict(self.by_priority),
            "avg_stage_ms": {k: round(v / n, 1) for k, v in self.stage_ms_sum.items()},
        }


stats = StatsTracker()
