"""Provider-agnostic LLM client factory.

Nodes only ever see the `LLMClient` protocol. Real providers go through LangChain's
`init_chat_model`, so switching provider is a config change (LLM_PROVIDER / LLM_MODEL).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from review_responder.config import Settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Providers where LangChain's default (a forced tool call) is rejected or worse than native
# JSON-schema output.
_JSON_SCHEMA_PROVIDERS = {"anthropic", "openai"}


class LLMClient(Protocol):
    model_name: str

    async def structured(
        self, system: str, user: str, schema: type[T], *, hints: dict[str, Any] | None = None
    ) -> T:
        """Return an instance of `schema`. `hints` carry raw inputs for offline/fake clients;
        real LLM clients ignore them."""
        ...


class LangChainLLM:
    def __init__(self, settings: Settings) -> None:
        from langchain.chat_models import init_chat_model

        kwargs: dict[str, Any] = {}
        if settings.llm_api_key:
            kwargs["api_key"] = settings.llm_api_key.get_secret_value()
        self._provider = settings.llm_provider
        self._chat = init_chat_model(
            settings.llm_model, model_provider=settings.llm_provider, **kwargs
        )
        method = settings.llm_structured_method
        if method == "auto":
            method = (
                "json_schema" if self._provider in _JSON_SCHEMA_PROVIDERS else "function_calling"
            )
        self._method = method
        self.model_name = f"{settings.llm_provider}:{settings.llm_model}"

    async def structured(
        self, system: str, user: str, schema: type[T], *, hints: dict[str, Any] | None = None
    ) -> T:
        runnable = self._chat.with_structured_output(schema, method=self._method)
        result = await runnable.ainvoke([("system", system), ("human", user)])
        if isinstance(result, schema):
            return result
        return schema.model_validate(result)


def get_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "offline":
        from review_responder.llm_offline import OfflineLLM

        return OfflineLLM()
    return LangChainLLM(settings)
