"""RAG-grounded triage: classify + pick assignment group via forced function calling.

The tool schema is generated from the TriageResult Pydantic model, so the LLM
contract and the application contract can never drift apart.
"""
import logging

from app.models import AssignmentGroup, Incident, KBHit, SimilarIncident, TriageResult
from app.services.llm import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert L1 IT service desk triage agent for an enterprise.
Your job: classify the incident and route it to exactly one enterprise team.

Rules:
- assignment_group MUST be one of the provided team names, verbatim.
- Ground your decision in the retrieved KB articles and similar past incidents.
  If several similar past incidents were routed to the same team, that is strong evidence.
- Set confidence honestly: use < 0.7 when evidence is thin or teams overlap.
- priority follows ITIL impact/urgency: 1 only for widespread outages or security incidents.
- suggested_resolution: concrete first steps the assignee should take, citing KB titles.
"""


def _triage_tool() -> dict:
    schema = TriageResult.model_json_schema()
    schema.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": "submit_triage",
            "description": "Submit the final triage and routing decision for the incident.",
            "parameters": schema,
        },
    }


class TriageService:
    def __init__(self, llm: LLMClient, groups: list[AssignmentGroup]):
        self._llm = llm
        self._groups = groups

    async def triage(self, incident: Incident, kb_hits: list[KBHit],
                     similar: list[SimilarIncident]) -> TriageResult:
        teams = "\n".join(
            f"- {g.name}: {g.description} (e.g. {', '.join(g.example_issues[:3])})"
            for g in self._groups
        )
        kb = "\n".join(f"[KB] {h.title} (sim={h.similarity}): {h.snippet}" for h in kb_hits) or "None found."
        past = "\n".join(
            f"[{s.number}] '{s.short_description}' -> routed to '{s.assignment_group}' "
            f"(sim={s.similarity}). Resolution: {s.resolution_notes[:200]}"
            for s in similar
        ) or "None found."

        user_msg = f"""## Incident
Number: {incident.number}
Short description: {incident.short_description}
Description: {incident.description}

## Available enterprise teams
{teams}

## Retrieved company KB articles
{kb}

## Similar past incidents (with historical routing)
{past}

Triage this incident now by calling submit_triage."""

        args = await self._llm.chat_with_tool(
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user_msg}],
            tool=_triage_tool(),
        )
        result = TriageResult(**args)

        # Guardrail: never trust the LLM blindly on the routing target
        valid_names = {g.name for g in self._groups}
        if result.assignment_group not in valid_names:
            logger.warning("LLM proposed unknown group '%s' — forcing low confidence", result.assignment_group)
            result.confidence = 0.0
        return result
