# 3-Minute Loom Demo Script

Target audience: hiring manager skimming your application. One take, screen +
voice, Claude Desktop on one side, terminal/PDI on the other.

## Setup before recording
- `APP_MODE=mock` in Claude Desktop config (zero-credential path), OR live PDI
  in a browser tab if Phase 2 is wired (much stronger).
- Restart Claude Desktop so the `incident-copilot` server loads.
- Terminal ready with `curl localhost:8000/stats | jq` typed but not run.

## Script

**[0:00–0:20] The problem.**
"L1 incident triage is manual, slow, and inconsistent. I built an AI copilot
that classifies, prioritizes, and routes ServiceNow incidents to the right
enterprise team automatically — grounded in company knowledge embeddings."

**[0:20–1:10] Zero-touch routing.**
(Live PDI variant): Create an incident in ServiceNow — "VPN keeps dropping since
this morning". Wait ~5s, refresh. "No human touched this: a Business Rule fired
a webhook, Azure OpenAI classified it using retrieved KB articles and similar
past incidents, and it's now assigned to Network Operations with an AI work note
explaining the reasoning and a suggested resolution."
(Mock variant): `curl -X POST localhost:8000/demo/run-all | jq` — "Six incidents
triaged and routed in under a second, each to the correct team."

**[1:10–2:10] The MCP angle.**
In Claude Desktop: "Triage the incident about the CEO gift card email and explain
your routing." Claude calls `triage_incident`, shows Security Operations at P1.
Then: "What are the routing stats for this session?" → `get_routing_stats`.
"The same service layer powers both a REST API and this MCP server — one
pipeline, two interfaces. Claude is operating my ServiceNow instance through it."

**[2:10–2:50] Engineering depth (screen: README architecture diagram).**
"Under the hood: FastAPI with async httpx and OAuth 2.0 against the Table API;
forced function calling with a Pydantic-generated schema so the AI contract
can't drift; a confidence gate that parks low-certainty tickets for human review;
correlation IDs on every log line; and a VectorStore protocol with three
backends — in-memory, Chroma, and Azure AI Search — swappable with one env var."

**[2:50–3:00] Close.**
"Repo's linked below — tests, CI, Docker, and a MuleSoft API-led design for the
enterprise topology. Runs in 60 seconds with zero credentials: APP_MODE=mock."
