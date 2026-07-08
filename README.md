# ServiceNow Incident Copilot

Zero-touch L1 incident triage: new incidents are automatically classified by Azure OpenAI, grounded in **company knowledge embeddings**, and routed to the right enterprise team in ServiceNow — no manual effort. Exposed as both a **FastAPI service** and an **MCP server** (connect it to Claude Desktop and triage incidents conversationally).

## How the zero-touch pipeline works

```
 ServiceNow                    Incident Copilot (FastAPI)                ServiceNow
┌───────────┐  Business Rule  ┌─────────────────────────────────┐  PATCH  ┌───────────┐
│ Incident   │───(webhook)───▶│ 1. Fetch incident (Table API)     │───────▶│ assignment │
│ created    │                │ 2. Embed & retrieve:              │        │ _group set │
└───────────┘                │    • company KB articles           │        │ + priority │
                              │    • similar past incidents        │        │ + category │
                              │      (with historical routing)     │        │ + AI work  │
                              │ 3. Azure OpenAI triage             │        │   note     │
                              │    (forced function calling →      │        └───────────┘
                              │     Pydantic-validated output)     │
                              │ 4. Confidence gate:                │
                              │    ≥ 0.7 → auto-route              │
                              │    < 0.7 → park in L1 queue        │
                              └─────────────────────────────────┘
```

Design decisions worth noting:

- **One `IncidentService` layer** serves both the REST API and the MCP tools — no duplicated logic.
- **The LLM tool schema is generated from the `TriageResult` Pydantic model**, so the AI contract and app contract can't drift.
- **Guardrails, not vibes**: the LLM can only route to teams in the catalog; hallucinated team names zero the confidence; low confidence falls back to a human queue with full reasoning in the work note.
- **Feedback loop**: `POST /learn/{sys_id}` indexes resolved incidents back into the vector store, so routing accuracy improves with history.

## Stack

FastAPI · Pydantic v2 · httpx (async) · OAuth 2.0 · ServiceNow Table API · Azure OpenAI (chat + embeddings, standard OpenAI fallback) · ChromaDB (swappable for Azure AI Search) · MCP (FastMCP) · Docker Compose · pytest + respx · GitHub Actions · structured JSON logging

## Quick start

```bash
cp .env.example .env          # fill in PDI + OpenAI credentials
pip install -r requirements.txt -r requirements-dev.txt
python -m scripts.seed_data --snow   # index KB + history, create demo incidents
uvicorn app.main:app --reload
```

Zero-touch setup: create the Business Rule + Outbound REST Message from
`integration/servicenow_business_rule.js` (use `ngrok http 8000` locally).
Now every new incident routes itself.

Manual demo without the webhook:

```bash
curl -X POST localhost:8000/triage/<sys_id> | jq
```

### MCP server (Claude Desktop)

```json
{
  "mcpServers": {
    "incident-copilot": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/servicenow-incident-copilot"
    }
  }
}
```

Then ask Claude: *"Triage incident INC0010023 and explain why you routed it there."*

### Docker

```bash
docker compose up --build
```

### Tests

```bash
pytest -v    # ServiceNow mocked with respx, LLM mocked — no credentials needed
```

## Enterprise topology (MuleSoft)

See [`integration/MULESOFT_DESIGN.md`](integration/MULESOFT_DESIGN.md) — API-led
connectivity design with a `servicenow-sapi` System API owning credentials and
policies. The client here is a one-file swap away from pointing at CloudHub.

## Roadmap

- Azure AI Search backend behind the existing `EmbeddingService` interface
- Multi-turn clarification: agent asks the caller for missing details via chat/email
- Routing accuracy dashboard (auto-routed vs. reassigned rate)
