"""Composition root: builds the live or mock dependency stack from APP_MODE.

This is the only place that knows which concrete implementations exist.
Everything downstream (routes, MCP tools, IncidentService) is implementation-blind.
"""
import json
import logging
from pathlib import Path

from app.config import Settings
from app.models import AssignmentGroup
from app.services.incident_service import IncidentService
from app.services.triage_service import TriageService

logger = logging.getLogger(__name__)


def load_groups() -> list[AssignmentGroup]:
    path = Path(__file__).parent.parent / "data" / "assignment_groups.json"
    return [AssignmentGroup(**g) for g in json.loads(path.read_text())]


def _build_vector_store(settings: Settings, llm):
    """Select the vector backend by config. Both satisfy the VectorStore protocol."""
    if settings.vector_backend == "azure_ai_search":
        from app.services.azure_search_store import AzureAISearchStore

        logger.info("Vector backend: Azure AI Search")
        return AzureAISearchStore(settings, llm)
    from app.services.embedding_service import EmbeddingService

    logger.info("Vector backend: ChromaDB")
    return EmbeddingService(settings, llm)


async def build_stack(settings: Settings) -> IncidentService:
    if settings.app_mode == "mock":
        from app.mocks.mock_llm import DeterministicLLM, InMemoryEmbeddings
        from app.mocks.mock_servicenow import MockServiceNowClient
        from scripts.seed_data import HISTORICAL_INCIDENTS, KB_ARTICLES

        logger.warning("APP_MODE=mock — running fully offline with deterministic AI")
        llm = DeterministicLLM()
        snow = MockServiceNowClient()
        emb = InMemoryEmbeddings(llm)
        await emb.index_kb_articles(KB_ARTICLES)
        for hid, desc, group, resolution in HISTORICAL_INCIDENTS:
            await emb.index_resolved_incident(hid, hid, desc, group, resolution)
    else:
        from app.services.llm import LLMClient
        from app.services.servicenow_client import ServiceNowClient

        logger.info("APP_MODE=live — ServiceNow: %s", settings.snow_instance_url)
        llm = LLMClient(settings)
        snow = ServiceNowClient(settings)
        emb = _build_vector_store(settings, llm)

    triage = TriageService(llm, load_groups())
    return IncidentService(snow, emb, triage, settings)
