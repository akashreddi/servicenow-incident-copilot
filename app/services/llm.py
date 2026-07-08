"""LLM + embedding client. Prefers Azure OpenAI; falls back to standard OpenAI.

The rest of the codebase never imports openai directly — swap providers here.
"""
import logging
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.config import Settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, settings: Settings):
        self._s = settings
        if settings.azure_openai_endpoint:
            logger.info("Using Azure OpenAI at %s", settings.azure_openai_endpoint)
            self._client: Any = AsyncAzureOpenAI(
                azure_endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_api_key,
                api_version=settings.azure_openai_api_version,
            )
            self.chat_model = settings.azure_openai_chat_deployment
            self.embed_model = settings.azure_openai_embedding_deployment
        else:
            logger.warning("AZURE_OPENAI_ENDPOINT not set — falling back to standard OpenAI")
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
            self.chat_model = "gpt-4o-mini"
            self.embed_model = "text-embedding-3-small"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.embeddings.create(model=self.embed_model, input=texts)
        return [d.embedding for d in resp.data]

    async def chat_with_tool(self, messages: list[dict], tool: dict) -> dict:
        """Force a single function call and return its parsed arguments."""
        import json

        resp = await self._client.chat.completions.create(
            model=self.chat_model,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": tool["function"]["name"]}},
            temperature=0.1,
        )
        call = resp.choices[0].message.tool_calls[0]
        return json.loads(call.function.arguments)
