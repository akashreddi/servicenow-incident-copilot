"""The contract every vector backend implements. Making it an explicit Protocol
means Chroma, Azure AI Search, and the in-memory mock are checked against one
interface — and IncidentService depends on this abstraction, not a concrete class.
"""
from typing import Protocol, runtime_checkable

from app.models import KBHit, SimilarIncident


@runtime_checkable
class VectorStore(Protocol):
    async def index_kb_articles(self, articles: list[dict]) -> int:
        """articles: [{id, title, body}]. Returns count indexed."""
        ...

    async def index_resolved_incident(self, sys_id: str, number: str, text: str,
                                      assignment_group: str, resolution_notes: str = "") -> None:
        ...

    async def search_kb(self, query: str, k: int = 3) -> list[KBHit]:
        ...

    async def search_similar_incidents(self, query: str, k: int = 5) -> list[SimilarIncident]:
        ...
