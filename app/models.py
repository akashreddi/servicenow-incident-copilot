"""Pydantic models — the contract between ServiceNow, the LLM, and the API."""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IncidentPriority(str, Enum):
    critical = "1"
    high = "2"
    moderate = "3"
    low = "4"
    planning = "5"


class Incident(BaseModel):
    """Subset of the ServiceNow ITSM incident table we care about."""
    sys_id: str
    number: str
    short_description: str
    description: str = ""
    category: str = ""
    subcategory: str = ""
    priority: str = ""
    urgency: str = ""
    impact: str = ""
    state: str = ""
    assignment_group: str = ""
    caller_id: str = ""
    opened_at: Optional[str] = None

    @property
    def text(self) -> str:
        return f"{self.short_description}\n{self.description}".strip()


class TriageResult(BaseModel):
    """Structured output the LLM must return (enforced via function calling)."""
    category: str = Field(description="ITSM category, e.g. Network, Software, Hardware, Database, Inquiry")
    subcategory: str = Field(default="", description="More specific subcategory if identifiable")
    priority: IncidentPriority = Field(description="1=Critical .. 5=Planning, per impact/urgency")
    assignment_group: str = Field(description="Exact name of the enterprise team to route to")
    confidence: float = Field(ge=0.0, le=1.0, description="Routing confidence 0..1")
    reasoning: str = Field(description="One-paragraph justification citing KB/similar incidents used")
    suggested_resolution: str = Field(default="", description="Draft resolution steps for the assignee")


class SimilarIncident(BaseModel):
    sys_id: str
    number: str
    short_description: str
    resolution_notes: str = ""
    assignment_group: str = ""
    similarity: float


class KBHit(BaseModel):
    doc_id: str
    title: str
    snippet: str
    similarity: float


class RoutingDecision(BaseModel):
    incident_sys_id: str
    incident_number: str
    triage: TriageResult
    similar_incidents: list[SimilarIncident] = []
    kb_hits: list[KBHit] = []
    routed_to: str
    auto_routed: bool  # False => fell back to L1 queue for human review
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WebhookPayload(BaseModel):
    """Payload sent by the ServiceNow Business Rule on incident insert."""
    sys_id: str
    number: str
    short_description: str
    description: str = ""
    caller_id: str = ""


class AssignmentGroup(BaseModel):
    """Enterprise team catalog entry — grounds the LLM's routing choice."""
    name: str
    description: str
    example_issues: list[str] = []
