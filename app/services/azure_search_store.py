"""Azure AI Search backend — same VectorStore contract as the Chroma service.

Uses vector search (HNSW) via the azure-search-documents SDK. Two indexes:
company KB and historical incidents. We push our own embeddings (from LLMClient)
as the vector field, so the same embedding model backs every backend and results
stay comparable.

Index creation is idempotent (create-if-missing), so `seed_data` just works.
Set VECTOR_BACKEND=azure_ai_search plus the AZURE_SEARCH_* vars to enable.
"""
import logging

from app.config import Settings
from app.models import KBHit, SimilarIncident
from app.services.llm import LLMClient

logger = logging.getLogger(__name__)

EMBED_DIM = 1536  # text-embedding-3-small


class AzureAISearchStore:
    def __init__(self, settings: Settings, llm: LLMClient):
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.aio import SearchClient

        self._llm = llm
        self._endpoint = settings.azure_search_endpoint
        self._cred = AzureKeyCredential(settings.azure_search_api_key)
        self._kb_index = settings.azure_search_kb_index
        self._inc_index = settings.azure_search_incident_index
        self._ensure_indexes()
        self._kb = SearchClient(self._endpoint, self._kb_index, self._cred)
        self._inc = SearchClient(self._endpoint, self._inc_index, self._cred)
        logger.info("Azure AI Search backend ready (%s)", self._endpoint)

    # ---------- index management ----------
    def _ensure_indexes(self) -> None:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.indexes import SearchIndexClient
        from azure.search.documents.indexes.models import (
            HnswAlgorithmConfiguration,
            SearchableField,
            SearchField,
            SearchFieldDataType,
            SearchIndex,
            SimpleField,
            VectorSearch,
            VectorSearchProfile,
        )

        client = SearchIndexClient(self._endpoint, AzureKeyCredential(self._cred.key))
        existing = {i for i in client.list_index_names()}

        vector_search = VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
            profiles=[VectorSearchProfile(name="vprofile", algorithm_configuration_name="hnsw")],
        )

        def vector_field() -> SearchField:
            return SearchField(
                name="vector", type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True, vector_search_dimensions=EMBED_DIM,
                vector_search_profile_name="vprofile",
            )

        if self._kb_index not in existing:
            client.create_index(SearchIndex(
                name=self._kb_index,
                fields=[
                    SimpleField(name="id", type=SearchFieldDataType.String, key=True),
                    SearchableField(name="title", type=SearchFieldDataType.String),
                    SearchableField(name="text", type=SearchFieldDataType.String),
                    vector_field(),
                ],
                vector_search=vector_search,
            ))
            logger.info("Created Azure Search index %s", self._kb_index)

        if self._inc_index not in existing:
            client.create_index(SearchIndex(
                name=self._inc_index,
                fields=[
                    SimpleField(name="id", type=SearchFieldDataType.String, key=True),
                    SimpleField(name="number", type=SearchFieldDataType.String),
                    SearchableField(name="short_description", type=SearchFieldDataType.String),
                    SearchableField(name="resolution_notes", type=SearchFieldDataType.String),
                    SimpleField(name="assignment_group", type=SearchFieldDataType.String,
                                filterable=True, facetable=True),
                    SearchableField(name="text", type=SearchFieldDataType.String),
                    vector_field(),
                ],
                vector_search=vector_search,
            ))
            logger.info("Created Azure Search index %s", self._inc_index)
        client.close()

    # ---------- ingestion ----------
    async def index_kb_articles(self, articles: list[dict]) -> int:
        texts = [f"{a['title']}\n{a['body']}" for a in articles]
        vectors = await self._llm.embed(texts)
        docs = [
            {"id": a["id"], "title": a["title"], "text": t, "vector": v}
            for a, t, v in zip(articles, texts, vectors)
        ]
        await self._kb.upload_documents(documents=docs)
        return len(docs)

    async def index_resolved_incident(self, sys_id: str, number: str, text: str,
                                      assignment_group: str, resolution_notes: str = "") -> None:
        [vec] = await self._llm.embed([text])
        await self._inc.upload_documents(documents=[{
            "id": sys_id, "number": number,
            "short_description": text.splitlines()[0][:200],
            "resolution_notes": resolution_notes[:1000],
            "assignment_group": assignment_group, "text": text, "vector": vec,
        }])

    # ---------- retrieval ----------
    async def search_kb(self, query: str, k: int = 3) -> list[KBHit]:
        results = await self._vector_query(self._kb, query, k)
        return [
            KBHit(doc_id=r["id"], title=r.get("title", ""),
                  snippet=r.get("text", "")[:400], similarity=round(r["@search.score"], 3))
            async for r in results
        ]

    async def search_similar_incidents(self, query: str, k: int = 5) -> list[SimilarIncident]:
        results = await self._vector_query(self._inc, query, k)
        return [
            SimilarIncident(
                sys_id=r["id"], number=r.get("number", ""),
                short_description=r.get("short_description", ""),
                resolution_notes=r.get("resolution_notes", ""),
                assignment_group=r.get("assignment_group", ""),
                similarity=round(r["@search.score"], 3))
            async for r in results
        ]

    async def _vector_query(self, client, query: str, k: int):
        from azure.search.documents.models import VectorizedQuery

        [vec] = await self._llm.embed([query])
        return await client.search(
            search_text=None,
            vector_queries=[VectorizedQuery(vector=vec, k_nearest_neighbors=k, fields="vector")],
            top=k,
        )
