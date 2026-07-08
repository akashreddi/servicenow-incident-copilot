"""FastAPI entrypoint.

The /webhook/incident endpoint is what makes this zero-touch: a ServiceNow
Business Rule (async, on insert) POSTs here, and BackgroundTasks runs the
full pipeline without blocking ServiceNow's outbound call.
"""
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request

from app.config import get_settings
from app.factory import build_stack
from app.models import RoutingDecision, WebhookPayload
from app.observability import correlation_id, new_correlation_id, setup_logging, stats
from app.services.incident_service import IncidentService

setup_logging(get_settings().log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.incident_service = await build_stack(settings)
    logger.info("Incident Copilot ready (mode=%s)", settings.app_mode)
    yield
    await app.state.incident_service._snow.aclose()


app = FastAPI(title="ServiceNow Incident Copilot", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    """Honor an inbound X-Correlation-ID (e.g. from MuleSoft) or mint a new one,
    and echo it back so callers can grep their logs against ours."""
    cid = request.headers.get("x-correlation-id") or new_correlation_id()
    correlation_id.set(cid)
    response = await call_next(request)
    response.headers["x-correlation-id"] = cid
    return response


@app.get("/stats")
async def get_stats() -> dict:
    """Routing-accuracy dashboard: auto-route rate, avg confidence, per-team
    distribution, per-stage latency. Counters map onto Prometheus if needed."""
    return stats.snapshot()


def get_service() -> IncidentService:
    return app.state.incident_service


def verify_webhook_secret(x_webhook_secret: str = Header(default="")) -> None:
    # Constant-time compare so a wrong secret can't be recovered via timing.
    if not hmac.compare_digest(x_webhook_secret, get_settings().webhook_shared_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/webhook/incident", status_code=202, dependencies=[Depends(verify_webhook_secret)])
async def incident_webhook(payload: WebhookPayload, background: BackgroundTasks,
                           svc: IncidentService = Depends(get_service)) -> dict:
    """Called by a ServiceNow Business Rule on incident insert. Returns 202
    immediately; triage + routing happen in the background."""
    logger.info("Webhook received for %s", payload.number)
    background.add_task(svc.process_incident, payload.sys_id)
    return {"accepted": True, "incident": payload.number}


@app.post("/triage/{sys_id}", response_model=RoutingDecision)
async def triage_incident(sys_id: str, svc: IncidentService = Depends(get_service)) -> RoutingDecision:
    """Synchronous triage — useful for demos and manual re-triage."""
    try:
        return await svc.process_incident(sys_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Triage failed for %s", sys_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/learn/{sys_id}", status_code=204)
async def learn(sys_id: str, svc: IncidentService = Depends(get_service)) -> None:
    """Index a resolved incident into the vector store (feedback loop)."""
    await svc.learn_from_resolution(sys_id)


@app.post("/demo/run-all")
async def demo_run_all(svc: IncidentService = Depends(get_service)) -> list[dict]:
    """One-call demo: triage every unassigned incident and return the decisions.
    Works instantly in APP_MODE=mock; in live mode it processes real PDI incidents."""
    incidents = await svc._snow.list_incidents(query="active=true^assignment_group=NULL", limit=10)
    results = []
    for inc in incidents:
        if inc.assignment_group:
            continue
        decision = await svc.process_incident(inc.sys_id)
        results.append({
            "incident": decision.incident_number,
            "short_description": inc.short_description,
            "routed_to": decision.routed_to,
            "auto_routed": decision.auto_routed,
            "confidence": decision.triage.confidence,
            "priority": decision.triage.priority.value,
            "top_similar": decision.similar_incidents[0].number if decision.similar_incidents else None,
        })
    return results
