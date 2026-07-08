"""Deterministic stand-ins for the LLM and vector store.

- DeterministicLLM.embed(): hashed bag-of-words vectors — stable, offline, instant.
- DeterministicLLM.chat_with_tool(): keyword-rule triage returning the exact same
  TriageResult schema the real model returns via function calling.
- InMemoryEmbeddings: cosine similarity over lists — same four methods as the
  Chroma-backed EmbeddingService, zero external dependencies.
"""
import hashlib
import logging
import math
import re

from app.models import KBHit, SimilarIncident

logger = logging.getLogger(__name__)

DIM = 256

# keyword -> (group, category, priority)
RULES: list[tuple[list[str], tuple[str, str, str]]] = [
    (["vpn", "network", "firewall", "dns", "wifi", "connectivity"],
     ("Network Operations", "Network", "2")),
    (["sap", "salesforce", "erp", "crm", "workday", "purchase order"],
     ("Enterprise Applications", "Software", "2")),
    (["phishing", "gift card", "suspicious", "malware", "ransomware", "security"],
     ("Security Operations", "Security", "1")),
    (["pod", "kubernetes", "aks", "pipeline", "deploy", "crashloop", "azure devops"],
     ("Cloud Platform", "Software", "2")),
    (["locked out", "password", "mfa", "sso", "account", "login"],
     ("Identity & Access Management", "Access", "3")),
    (["printer", "laptop", "desktop", "blue screen", "bsod", "outlook", "monitor"],
     ("End User Computing", "Hardware", "3")),
    (["database", "oracle", "sql", "query", "connection pool"],
     ("Database Administration", "Database", "2")),
]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class DeterministicLLM:
    """Same public surface as LLMClient: embed() and chat_with_tool()."""

    chat_model = "deterministic-mock"
    embed_model = "hashed-bow-256"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * DIM
            for tok in _tokenize(text):
                idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM
                vec[idx] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out

    async def chat_with_tool(self, messages: list[dict], tool: dict) -> dict:
        """Keyword-rule triage. Scores ONLY the '## Incident' section of the prompt —
        scoring the whole prompt would leak keywords from the team catalog and
        retrieved KB text into the match (a real bug we hit in testing)."""
        full = messages[-1]["content"]
        incident_part = full.split("## Available", 1)[0].lower()
        best, hits = None, 0
        for keywords, target in RULES:
            n = sum(1 for k in keywords if k in incident_part)
            if n > hits:
                best, hits = target, n
        if best is None:
            return {
                "category": "Inquiry", "subcategory": "", "priority": "4",
                "assignment_group": "L1 Service Desk", "confidence": 0.3,
                "reasoning": "[mock] No strong keyword evidence; parking for human triage.",
                "suggested_resolution": "Gather more details from the caller.",
            }
        group, category, priority = best
        confidence = min(0.6 + 0.15 * hits, 0.95)
        return {
            "category": category, "subcategory": "", "priority": priority,
            "assignment_group": group, "confidence": round(confidence, 2),
            "reasoning": f"[mock] Matched {hits} domain keyword(s) for {group}; "
                         f"consistent with retrieved historical routing.",
            "suggested_resolution": f"Follow the {category} runbook steps referenced in the KB hits.",
        }


class InMemoryEmbeddings:
    """Same interface as EmbeddingService, backed by plain lists + cosine."""

    def __init__(self, llm: DeterministicLLM):
        self._llm = llm
        self._kb: list[dict] = []
        self._inc: list[dict] = []

    @staticmethod
    def _cos(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))  # vectors are pre-normalized

    async def index_kb_articles(self, articles: list[dict]) -> int:
        texts = [f"{a['title']}\n{a['body']}" for a in articles]
        vecs = await self._llm.embed(texts)
        for a, t, v in zip(articles, texts, vecs):
            self._kb.append({"id": a["id"], "title": a["title"], "text": t, "vec": v})
        return len(articles)

    async def index_resolved_incident(self, sys_id: str, number: str, text: str,
                                      assignment_group: str, resolution_notes: str = "") -> None:
        [vec] = await self._llm.embed([text])
        self._inc.append({
            "sys_id": sys_id, "number": number, "text": text, "vec": vec,
            "assignment_group": assignment_group, "resolution_notes": resolution_notes,
        })

    async def search_kb(self, query: str, k: int = 3) -> list[KBHit]:
        [q] = await self._llm.embed([query])
        scored = sorted(self._kb, key=lambda d: -self._cos(q, d["vec"]))[:k]
        return [KBHit(doc_id=d["id"], title=d["title"], snippet=d["text"][:400],
                      similarity=round(self._cos(q, d["vec"]), 3)) for d in scored]

    async def search_similar_incidents(self, query: str, k: int = 5) -> list[SimilarIncident]:
        [q] = await self._llm.embed([query])
        scored = sorted(self._inc, key=lambda d: -self._cos(q, d["vec"]))[:k]
        return [SimilarIncident(
            sys_id=d["sys_id"], number=d["number"],
            short_description=d["text"].splitlines()[0][:200],
            resolution_notes=d["resolution_notes"], assignment_group=d["assignment_group"],
            similarity=round(self._cos(q, d["vec"]), 3)) for d in scored]
