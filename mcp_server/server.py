"""MCP server — exposes the SAME IncidentService to any MCP client
(Claude Desktop, IDEs, agents). Run: python -m mcp_server.server

Demo script: connect this to Claude Desktop and ask
"Triage incident INC0010023 and tell me why you routed it there."
"""
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app.config import get_settings
from app.models import AssignmentGroup
from app.services.embedding_service import EmbeddingService
from app.services.incident_service import IncidentService
from app.services.llm import LLMClient
from app.services.servicenow_client import ServiceNowClient
from app.services.triage_service import TriageService

mcp = FastMCP("servicenow-incident-copilot")

_settings = get_settings()
_llm = LLMClient(_settings)
_snow = ServiceNowClient(_settings)
_emb = EmbeddingService(_settings, _llm)
_groups = [AssignmentGroup(**g) for g in json.loads(
    (Path(__file__).parent.parent / "data" / "assignment_groups.json").read_text())]
_service = IncidentService(_snow, _emb, TriageService(_llm, _groups), _settings)


@mcp.tool()
async def search_incidents(query: str = "active=true", limit: int = 10) -> str:
    """Search ServiceNow incidents using an encoded query (e.g. 'active=true^priority=1')."""
    incidents = await _snow.list_incidents(query=query, limit=limit)
    return json.dumps([i.model_dump() for i in incidents], indent=2)


@mcp.tool()
async def get_incident(sys_id: str) -> str:
    """Fetch a single incident by sys_id, including description and current assignment."""
    inc = await _snow.get_incident(sys_id)
    return inc.model_dump_json(indent=2)


@mcp.tool()
async def find_similar_incidents(text: str, k: int = 5) -> str:
    """Vector-search historical incidents similar to the given text, with past routing."""
    hits = await _emb.search_similar_incidents(text, k=k)
    return json.dumps([h.model_dump() for h in hits], indent=2)


@mcp.tool()
async def search_knowledge_base(query: str, k: int = 3) -> str:
    """Semantic search over the company knowledge base / runbooks."""
    hits = await _emb.search_kb(query, k=k)
    return json.dumps([h.model_dump() for h in hits], indent=2)


@mcp.tool()
async def triage_incident(sys_id: str) -> str:
    """Run the full AI triage pipeline: classify, find similar incidents, route to
    the right enterprise team in ServiceNow, and write an audit work note."""
    decision = await _service.process_incident(sys_id)
    return decision.model_dump_json(indent=2)


@mcp.tool()
async def add_work_note(sys_id: str, note: str) -> str:
    """Append a work note to an incident."""
    await _snow.add_work_note(sys_id, note)
    return f"Work note added to {sys_id}"


if __name__ == "__main__":
    mcp.run()
