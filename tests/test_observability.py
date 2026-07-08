"""Tests for correlation IDs and stats aggregation."""
import logging

import pytest

from app.config import Settings
from app.factory import build_stack
from app.observability import (
    CorrelationFilter,
    StageTimer,
    StatsTracker,
    correlation_id,
    new_correlation_id,
)


def test_correlation_id_is_set_and_unique():
    a = new_correlation_id()
    b = new_correlation_id()
    assert a != b
    assert correlation_id.get() == b
    assert len(a) == 8


def test_correlation_filter_injects_cid():
    new_correlation_id()
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "msg", None, None)
    assert CorrelationFilter().filter(rec) is True
    assert rec.cid == correlation_id.get()


def test_stage_timer_records_ms():
    t = StageTimer()
    with t.stage("retrieval"):
        sum(range(1000))
    assert "retrieval" in t.timings_ms
    assert t.timings_ms["retrieval"] >= 0


@pytest.mark.asyncio
async def test_stats_snapshot_after_pipeline_run():
    tracker = StatsTracker()
    settings = Settings(app_mode="mock", _env_file=None)
    svc = await build_stack(settings)
    incidents = await svc._snow.list_incidents()
    for inc in incidents[:3]:
        decision = await svc.process_incident(inc.sys_id)
        tracker.record(decision, {"retrieval": 5.0, "triage": 10.0, "writeback": 2.0})
    snap = tracker.snapshot()
    assert snap["processed"] == 3
    assert 0.0 <= snap["auto_route_rate"] <= 1.0
    assert snap["avg_stage_ms"]["triage"] == 10.0
    assert sum(snap["by_group"].values()) == 3
