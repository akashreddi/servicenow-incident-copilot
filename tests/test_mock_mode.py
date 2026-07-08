"""End-to-end test of the full pipeline in mock mode — no network, no credentials.
This is the same stack `APP_MODE=mock` runs in production."""
import pytest

from app.config import Settings
from app.factory import build_stack


@pytest.fixture
async def service():
    settings = Settings(app_mode="mock", _env_file=None)
    return await build_stack(settings)


@pytest.mark.asyncio
async def test_full_pipeline_routes_all_demo_incidents(service):
    incidents = await service._snow.list_incidents()
    expected = {
        "Cannot access VPN": "Network Operations",
        "SAP purchase order": "Enterprise Applications",
        "Strange email from CEO": "Security Operations",
        "Pipeline deploy failing": "Cloud Platform",
        "Locked out of my account": "Identity & Access Management",
        "Printer on floor 3": "End User Computing",
    }
    for inc in incidents:
        decision = await service.process_incident(inc.sys_id)
        match = next((g for k, g in expected.items() if inc.short_description.startswith(k)), None)
        assert match, f"unexpected demo incident: {inc.short_description}"
        assert decision.routed_to == match, f"{inc.short_description} misrouted to {decision.routed_to}"
        assert decision.auto_routed is True
        # audit trail written back
        record = service._snow._incidents[inc.sys_id]
        assert record["work_notes_log"], "work note missing"


@pytest.mark.asyncio
async def test_phishing_gets_p1(service):
    incidents = await service._snow.list_incidents()
    phishing = next(i for i in incidents if "gift card" in i.short_description.lower()
                    or "CEO" in i.short_description)
    decision = await service.process_incident(phishing.sys_id)
    assert decision.triage.priority.value == "1"
