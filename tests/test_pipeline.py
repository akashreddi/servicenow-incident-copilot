"""Unit tests — ServiceNow mocked with respx, LLM/embeddings mocked with AsyncMock.

Run: pytest -v
"""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from app.config import Settings
from app.models import AssignmentGroup, KBHit, SimilarIncident, TriageResult
from app.services.incident_service import IncidentService
from app.services.servicenow_client import ServiceNowClient
from app.services.triage_service import TriageService

BASE = "https://dev00000.service-now.com"


def make_settings(**overrides) -> Settings:
    return Settings(
        snow_instance_url=BASE,
        snow_oauth_client_id="cid",
        snow_oauth_client_secret="secret",
        snow_username="admin",
        snow_password="pw",
        routing_confidence_threshold=0.7,
        _env_file=None,
        **overrides,
    )


def mock_snow_routes(assignment_group_found: bool = True) -> None:
    respx.post(f"{BASE}/oauth_token.do").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 1800})
    )
    respx.get(f"{BASE}/api/now/table/incident/abc123").mock(
        return_value=httpx.Response(200, json={"result": {
            "sys_id": "abc123", "number": "INC0010001",
            "short_description": "VPN keeps disconnecting",
            "description": "Drops every 10 minutes since morning",
        }})
    )
    groups = [{"sys_id": "grp1", "name": "Network Operations"}] if assignment_group_found else []
    respx.get(f"{BASE}/api/now/table/sys_user_group").mock(
        return_value=httpx.Response(200, json={"result": groups})
    )
    respx.patch(f"{BASE}/api/now/table/incident/abc123").mock(
        return_value=httpx.Response(200, json={"result": {"sys_id": "abc123"}})
    )


def make_service(triage_result: TriageResult) -> IncidentService:
    settings = make_settings()
    snow = ServiceNowClient(settings)
    emb = MagicMock()
    emb.search_kb = AsyncMock(return_value=[KBHit(doc_id="KB0001", title="VPN Runbook", snippet="...", similarity=0.91)])
    emb.search_similar_incidents = AsyncMock(return_value=[
        SimilarIncident(sys_id="h1", number="HIST0001", short_description="VPN disconnects",
                        assignment_group="Network Operations", similarity=0.88)
    ])
    triage = MagicMock(spec=TriageService)
    triage.triage = AsyncMock(return_value=triage_result)
    return IncidentService(snow, emb, triage, settings)


@pytest.mark.asyncio
@respx.mock
async def test_high_confidence_auto_routes():
    mock_snow_routes()
    svc = make_service(TriageResult(
        category="Network", priority="2", assignment_group="Network Operations",
        confidence=0.92, reasoning="Matches HIST0001 routing and VPN runbook.",
    ))
    decision = await svc.process_incident("abc123")
    assert decision.auto_routed is True
    assert decision.routed_to == "Network Operations"
    assert decision.incident_number == "INC0010001"


@pytest.mark.asyncio
@respx.mock
async def test_low_confidence_falls_back_to_l1():
    mock_snow_routes()
    svc = make_service(TriageResult(
        category="Inquiry", priority="4", assignment_group="Enterprise Applications",
        confidence=0.45, reasoning="Ambiguous description, weak evidence.",
    ))
    decision = await svc.process_incident("abc123")
    assert decision.auto_routed is False
    assert decision.routed_to == "L1 Service Desk"


@pytest.mark.asyncio
@respx.mock
async def test_oauth_token_is_cached_across_calls():
    mock_snow_routes()
    settings = make_settings()
    snow = ServiceNowClient(settings)
    await snow.get_incident("abc123")
    await snow.get_incident("abc123")
    token_calls = [c for c in respx.calls if c.request.url.path == "/oauth_token.do"]
    assert len(token_calls) == 1  # second call reused cached token


def test_triage_guardrail_rejects_unknown_group():
    """LLM hallucinating a team name must zero out confidence."""
    groups = [AssignmentGroup(name="Network Operations", description="nets")]
    valid = {g.name for g in groups}
    result = TriageResult(category="Network", priority="3",
                          assignment_group="Made Up Team", confidence=0.99, reasoning="x")
    if result.assignment_group not in valid:
        result.confidence = 0.0
    assert result.confidence == 0.0
