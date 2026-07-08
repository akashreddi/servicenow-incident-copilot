"""Vector search over (1) company KB articles and (2) historical routed incidents.

ChromaDB locally for the weekend build; the interface is deliberately thin so
Azure AI Search can be swapped in behind the same three methods.
"""
import logging

from app.config import Settings
from app.models import KBHit, SimilarIncident
from app.services.llm import LLMClient

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, settings: Settings, llm: LLMClient):
        import chromadb  # lazy import: keeps unit tests light

        self._llm = llm
        if settings.chroma_host:
            self._db = chromadb.HttpClient(host=settings.chroma_host, port=8000)
        else:
            self._db = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        self._kb = self._db.get_or_create_collection(settings.kb_collection)
        self._inc = self._db.get_or_create_collection(settings.incident_collection)

    # ---------- ingestion ----------
    async def index_kb_articles(self, articles: list[dict]) -> int:
        """articles: [{id, title, body}] — company knowledge base / runbooks."""
        texts = [f"{a['title']}\n{a['body']}" for a in articles]
        vectors = await self._llm.embed(texts)
        self._kb.upsert(
            ids=[a["id"] for a in articles],
            embeddings=vectors,
            documents=texts,
            metadatas=[{"title": a["title"]} for a in articles],
        )
        return len(articles)

    async def index_resolved_incident(self, sys_id: str, number: str, text: str,
                                      assignment_group: str, resolution_notes: str = "") -> None:
        [vec] = await self._llm.embed([text])
        self._inc.upsert(
            ids=[sys_id],
            embeddings=[vec],
            documents=[text],
            metadatas=[{
                "number": number,
                "assignment_group": assignment_group,
                "resolution_notes": resolution_notes[:1000],
                "short_description": text.splitlines()[0][:200],
            }],
        )

    # ---------- retrieval ----------
    async def search_kb(self, query: str, k: int = 3) -> list[KBHit]:
        [vec] = await self._llm.embed([query])
        res = self._kb.query(query_embeddings=[vec], n_results=k)
        return [
            KBHit(
                doc_id=res["ids"][0][i],
                title=res["metadatas"][0][i].get("title", ""),
                snippet=res["documents"][0][i][:400],
                similarity=round(1 - res["distances"][0][i], 3),
            )
            for i in range(len(res["ids"][0]))
        ]

    async def search_similar_incidents(self, query: str, k: int = 5) -> list[SimilarIncident]:
        [vec] = await self._llm.embed([query])
        res = self._inc.query(query_embeddings=[vec], n_results=k)
        return [
            SimilarIncident(
                sys_id=res["ids"][0][i],
                number=res["metadatas"][0][i].get("number", ""),
                short_description=res["metadatas"][0][i].get("short_description", ""),
                resolution_notes=res["metadatas"][0][i].get("resolution_notes", ""),
                assignment_group=res["metadatas"][0][i].get("assignment_group", ""),
                similarity=round(1 - res["distances"][0][i], 3),
            )
            for i in range(len(res["ids"][0]))
        ]
