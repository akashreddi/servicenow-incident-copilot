"""All vector backends must satisfy the same VectorStore protocol.

We can't hit real Azure/Chroma in CI, but we CAN assert every implementation
conforms to the shared interface — that's what makes them swappable.
"""
from app.mocks.mock_llm import DeterministicLLM, InMemoryEmbeddings
from app.services.vector_store import VectorStore


def test_inmemory_backend_conforms_to_protocol():
    store = InMemoryEmbeddings(DeterministicLLM())
    assert isinstance(store, VectorStore)


def test_all_backends_share_method_signatures():
    """Structural check: the three backends expose identical method names."""
    import inspect

    from app.services.azure_search_store import AzureAISearchStore
    from app.services.embedding_service import EmbeddingService

    required = {"index_kb_articles", "index_resolved_incident",
                "search_kb", "search_similar_incidents"}
    for cls in (EmbeddingService, AzureAISearchStore, InMemoryEmbeddings):
        methods = {n for n, _ in inspect.getmembers(cls, inspect.isfunction)}
        assert required <= methods, f"{cls.__name__} missing {required - methods}"


async def test_inmemory_roundtrip():
    store = InMemoryEmbeddings(DeterministicLLM())
    await store.index_kb_articles([{"id": "K1", "title": "VPN", "body": "reset the anyconnect profile"}])
    hits = await store.search_kb("vpn not connecting", k=1)
    assert hits and hits[0].doc_id == "K1"
