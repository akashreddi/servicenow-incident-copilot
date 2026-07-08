"""IncidentService — single orchestration layer used by BOTH FastAPI routes
and MCP tools. This is the zero-touch L1 pipeline:

  webhook -> fetch incident -> RAG retrieval (KB + past incidents)
         -> LLM triage/function-call -> confidence gate
         -> auto-route in ServiceNow -> audit work note
"""
import logging

from app.config import Settings
from app.models import Incident, RoutingDecision
from app.services.embedding_service import EmbeddingService
from app.services.servicenow_client import ServiceNowClient
from app.services.triage_service import TriageService

logger = logging.getLogger(__name__)


class IncidentService:
    def __init__(self, snow: ServiceNowClient, embeddings: EmbeddingService,
                 triage: TriageService, settings: Settings):
        self._snow = snow
        self._emb = embeddings
        self._triage = triage
        self._s = settings

    async def process_incident(self, sys_id: str) -> RoutingDecision:
        """End-to-end auto-triage for one incident. Idempotent and audit-logged."""
        incident = await self._snow.get_incident(sys_id)
        logger.info("Processing %s: %s", incident.number, incident.short_description)

        # 1. Retrieval — company embeddings ground the decision
        kb_hits = await self._emb.search_kb(incident.text, k=3)
        similar = await self._emb.search_similar_incidents(incident.text, k=5)

        # 2. LLM triage with forced structured output
        triage = await self._triage.triage(incident, kb_hits, similar)

        # 3. Confidence gate: auto-route or park in fallback L1 queue
        auto = triage.confidence >= self._s.routing_confidence_threshold
        target_group = triage.assignment_group if auto else self._s.fallback_assignment_group

        # 4. Write back to ServiceNow
        fields: dict = {
            "category": triage.category.lower(),
            "priority": triage.priority.value,
        }
        group_sys_id = await self._snow.resolve_group_sys_id(target_group)
        if group_sys_id:
            fields["assignment_group"] = group_sys_id
        await self._snow.update_incident(sys_id, fields)

        note = self._format_work_note(triage, target_group, auto, similar)
        await self._snow.add_work_note(sys_id, note)

        decision = RoutingDecision(
            incident_sys_id=sys_id,
            incident_number=incident.number,
            triage=triage,
            similar_incidents=similar,
            kb_hits=kb_hits,
            routed_to=target_group,
            auto_routed=auto,
        )
        logger.info("Routed %s -> %s (auto=%s, confidence=%.2f)",
                    incident.number, target_group, auto, triage.confidence)
        return decision

    async def learn_from_resolution(self, sys_id: str) -> None:
        """Feedback loop: index a resolved incident so future routing improves."""
        inc = await self._snow.get_incident(sys_id)
        await self._emb.index_resolved_incident(
            sys_id=inc.sys_id, number=inc.number, text=inc.text,
            assignment_group=inc.assignment_group,
        )

    @staticmethod
    def _format_work_note(triage, target_group: str, auto: bool, similar) -> str:
        header = "🤖 AI Auto-Triage" if auto else "🤖 AI Triage — LOW CONFIDENCE, parked for human review"
        refs = ", ".join(s.number for s in similar[:3]) or "none"
        return (
            f"{header}\n"
            f"Routed to: {target_group} (confidence {triage.confidence:.0%})\n"
            f"Category: {triage.category}/{triage.subcategory} | Priority: {triage.priority.value}\n"
            f"Similar incidents: {refs}\n"
            f"Reasoning: {triage.reasoning}\n\n"
            f"Suggested resolution:\n{triage.suggested_resolution}"
        )
