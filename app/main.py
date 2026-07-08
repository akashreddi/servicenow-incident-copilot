"""FastAPI entrypoint.

The /webhook/incident endpoint is what makes this zero-touch: a ServiceNow
Business Rule (async, on insert) POSTs here, and BackgroundTasks runs the
full pipeline without blocking ServiceNow's outbound call.
"""
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.models import AssignmentGroup, RoutingDecision, WebhookPayload
from app.services.embedding_service import EmbeddingService
from app.services.incident_service import IncidentService
from app.services.llm import LLMClient
from app.services.servicenow_client import ServiceNowClient
from app.services.triage_service import TriageService

logging.basicConfig(
    level=get_settings().log_level,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)


def load_groups() -> list[AssignmentGroup]:
    path = Path(__file__).parent.parent / "data" / "assignment_groups.json"
    return [AssignmentGroup(**g) for g in json.loads(path.read_text())]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    llm = LLMClient(settings)
    snow = ServiceNowClient(settings)
    embeddings = EmbeddingService(settings, llm)
    triage = TriageService(llm, load_groups())
    app.state.incident_service = IncidentService(snow, embeddings, triage, settings)
    logger.info("Incident Copilot ready")
    yield
    await snow.aclose()


app = FastAPI(title="ServiceNow Incident Copilot", version="0.1.0", lifespan=lifespan)


def get_service() -> IncidentService:
    return app.state.incident_service


def verify_webhook_secret(x_webhook_secret: str = Header(default="")) -> None:
    if x_webhook_secret != get_settings().webhook_shared_secret:
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
        return JSONResponse(status_code=502, content={"error": str(exc)})


@app.post("/learn/{sys_id}", status_code=204)
async def learn(sys_id: str, svc: IncidentService = Depends(get_service)) -> None:
    """Index a resolved incident into the vector store (feedback loop)."""
    await svc.learn_from_resolution(sys_id)
