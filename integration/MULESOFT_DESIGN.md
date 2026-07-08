# MuleSoft Integration Design (API-Led Connectivity)

In an enterprise deployment, the Copilot would not call ServiceNow directly.
MuleSoft sits between them following API-led connectivity:

```
┌─────────────────────┐        ┌──────────────────────────┐        ┌──────────────┐
│ Incident Copilot     │  REST  │  MuleSoft (CloudHub)      │  REST  │  ServiceNow   │
│ (FastAPI + Azure     │──────▶│                           │──────▶│  Table API    │
│  OpenAI + Chroma)    │        │  Process API:             │        │               │
│                      │◀──────│   incident-triage-papi     │◀──────│  Business Rule│
└─────────────────────┘ webhook│  System API:               │ event  └──────────────┘
                                │   servicenow-sapi          │
                                └──────────────────────────┘
```

## Why the layer exists

- **System API (`servicenow-sapi`)**: owns ServiceNow credentials/OAuth, rate limiting,
  and schema mapping. The Copilot never holds ServiceNow secrets in this topology.
- **Process API (`incident-triage-papi`)**: orchestrates webhook fan-out, retries with
  DLQ (Anypoke MQ), and can enrich the payload (CMDB lookups, user context) before
  the Copilot sees it.
- **Policies on API Manager**: client-id enforcement, spike control, JSON threat protection.

## Minimal spec (OAS 3) — servicenow-sapi

```yaml
openapi: 3.0.3
info: { title: servicenow-sapi, version: 1.0.0 }
paths:
  /incidents/{sysId}:
    get:
      summary: Get incident
      responses: { "200": { description: Incident } }
    patch:
      summary: Update incident (assignment_group, category, priority, work_notes)
      responses: { "200": { description: Updated } }
  /incidents:
    get:
      summary: Query incidents (sysparm_query passthrough, allow-listed fields)
      responses: { "200": { description: Incident list } }
  /groups:
    get:
      summary: Resolve assignment group name -> sys_id
      responses: { "200": { description: Group } }
```

## Migration path in this repo

`app/services/servicenow_client.py` is the only file that knows ServiceNow's URL shape.
Pointing `SNOW_INSTANCE_URL` at the Mule System API and adjusting paths is a
one-file change — the pipeline, MCP server, and API are untouched.

## If demonstrating live (optional, ~2h)

1. 30-day Anypoint trial → Design Center: import the OAS above.
2. Flow: HTTP Listener → HTTP Request to PDI (OAuth via client credentials).
3. Deploy to CloudHub sandbox, apply client-id enforcement policy.
4. Point the Copilot's `.env` at the CloudHub URL.
