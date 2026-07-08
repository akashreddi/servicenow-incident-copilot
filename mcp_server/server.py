"""MCP server — exposes the SAME IncidentService pipeline to any MCP client
(Claude Desktop, IDEs, agents), via the same factory as the FastAPI app.

APP_MODE=mock  -> demo anywhere, zero credentials (in-memory ServiceNow + rule LLM)
APP_MODE=live  -> real PDI + Azure OpenAI

Run: python -m mcp_server.server
"""
import json

from mcp.server.fastmcp import FastMCP

from app.config import get_settings
from app.factory import build_stack
from app.observability import stats

mcp = FastMCP("servicenow-incident-copilot")

_service = None


async def service():
    """Lazy singleton: build the (async) stack on first tool call."""
    global _service
    if _service is None:
        _service = await build_stack(get_settings())
    return _service


@mcp.tool()
async def search_incidents(query: str = "active=true", limit: int = 10) -> str:
    """Search ServiceNow incidents using an encoded query (e.g. 'active=true^priority=1')."""
    svc = await service()
    incidents = await svc._snow.list_incidents(query=query, limit=limit)
    return json.dumps([i.model_dump() for i in incidents], indent=2)


@mcp.tool()
async def get_incident(sys_id: str) -> str:
    """Fetch a single incident by sys_id, including description and current assignment."""
    svc = await service()
    inc = await svc._snow.get_incident(sys_id)
    return inc.model_dump_json(indent=2)


@mcp.tool()
async def find_similar_incidents(text: str, k: int = 5) -> str:
    """Vector-search historical incidents similar to the given text, with past routing."""
    svc = await service()
    hits = await svc._emb.search_similar_incidents(text, k=k)
    return json.dumps([h.model_dump() for h in hits], indent=2)


@mcp.tool()
async def search_knowledge_base(query: str, k: int = 3) -> str:
    """Semantic search over the company knowledge base / runbooks."""
    svc = await service()
    hits = await svc._emb.search_kb(query, k=k)
    return json.dumps([h.model_dump() for h in hits], indent=2)


@mcp.tool()
async def triage_incident(sys_id: str) -> str:
    """Run the full AI triage pipeline: classify, find similar incidents, route to
    the right enterprise team in ServiceNow, and write an audit work note."""
    svc = await service()
    decision = await svc.process_incident(sys_id)
    return decision.model_dump_json(indent=2)


@mcp.tool()
async def add_work_note(sys_id: str, note: str) -> str:
    """Append a work note to an incident."""
    svc = await service()
    await svc._snow.add_work_note(sys_id, note)
    return f"Work note added to {sys_id}"


@mcp.tool()
async def get_routing_stats() -> str:
    """Routing dashboard for this session: auto-route rate, avg confidence,
    per-team and per-priority distribution, per-stage latency."""
    return json.dumps(stats.snapshot(), indent=2)


if __name__ == "__main__":
    mcp.run()
