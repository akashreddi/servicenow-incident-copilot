# Phase 2: Live PDI Setup Checklist (~30 min)

## 1. Get a Personal Developer Instance (5 min)
1. Sign up / log in at https://developer.servicenow.com
2. Request an instance (latest release). Note your instance URL: `https://devNNNNNN.service-now.com`
3. Note the auto-generated **admin password** (shown once — save it).
   PDIs hibernate after inactivity; wake them from the developer portal.

## 2. OAuth 2.0 Application Registry (5 min)
1. In your PDI: **System OAuth > Application Registry > New**
2. Choose **"Create an OAuth API endpoint for external clients"**
3. Name: `incident-copilot`. Leave redirect URL empty.
4. Save, then reopen the record → copy **Client ID** and **Client Secret**.
5. PDIs work best with the **password grant** (resource owner):
   the client credentials grant needs extra plugin setup, so `.env` uses
   `SNOW_OAUTH_GRANT_TYPE=password` + your admin user/password alongside
   the client id/secret. (In a customer environment you'd use
   client_credentials or an integration user — mention this in interviews.)

## 3. Fill .env and run preflight (5 min)
```bash
cp .env.example .env   # set APP_MODE=live, SNOW_*, AZURE_OPENAI_* / OPENAI_API_KEY
python -m scripts.preflight --fix-groups
```
Preflight validates: config → OAuth → Table API → assignment groups
(creates the 8 enterprise teams if missing) → embeddings → function calling.
Fix whatever it flags; rerun until 🚀.

## 4. Seed knowledge + demo incidents (2 min)
```bash
python -m scripts.seed_data --snow
```
Indexes 7 KB articles + 14 historical routed incidents into Chroma, and creates
5 fresh unassigned incidents in the PDI.

## 5. First live triage (2 min)
```bash
uvicorn app.main:app --port 8000
curl -X POST localhost:8000/demo/run-all | jq
```
Then open **Incident > All** in the PDI: assignment groups set, AI work notes attached.

## 6. Zero-touch webhook (10 min)
1. Expose your service: `ngrok http 8000` → copy the https URL.
2. PDI: **System Web Services > Outbound > REST Message > New**
   - Name: `Incident Copilot Webhook`; Endpoint: `https://<ngrok>/webhook/incident`
   - HTTP Method record `Default POST`; add header `x-webhook-secret: <your WEBHOOK_SHARED_SECRET>`
3. **System Definition > Business Rules > New** on table `incident`,
   When: **async**, Insert: ✔, Condition: `assignment_group ISEMPTY`
   Script: paste `integration/servicenow_business_rule.js` (inner function body).
4. Test: create an incident manually in the PDI ("VPN not working from home")
   → within seconds it's categorized, prioritized, routed, with an AI work note.

**That moment — creating a ticket and watching it route itself — is your Loom demo.**
