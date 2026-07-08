"""MCP tools must work end-to-end in mock mode — same pipeline, second interface."""
import json

import pytest

import mcp_server.server as srv


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch):
    monkeypatch.setenv("APP_MODE", "mock")
    from app.config import get_settings
    get_settings.cache_clear()
    srv._service = None
    yield
    get_settings.cache_clear()
    srv._service = None


@pytest.mark.asyncio
async def test_search_and_triage_via_mcp_tools():
    raw = await srv.search_incidents()
    incidents = json.loads(raw)
    assert len(incidents) >= 5

    vpn = next(i for i in incidents if "VPN" in i["short_description"])
    decision = json.loads(await srv.triage_incident(vpn["sys_id"]))
    assert decision["routed_to"] == "Network Operations"
    assert decision["auto_routed"] is True


@pytest.mark.asyncio
async def test_kb_search_tool():
    hits = json.loads(await srv.search_knowledge_base("phishing email response"))
    assert hits and "Phishing" in hits[0]["title"]


@pytest.mark.asyncio
async def test_stats_tool_reports_after_triage():
    incidents = json.loads(await srv.search_incidents())
    await srv.triage_incident(incidents[0]["sys_id"])
    snap = json.loads(await srv.get_routing_stats())
    assert snap["processed"] >= 1
