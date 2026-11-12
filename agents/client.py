"""Bounded local inference shared by the review agents."""

import httpx
from langchain_ollama import ChatOllama

from agents.transport import retry_ollama, retry_ollama_async
from config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_REASONING,
    OLLAMA_REQUEST_TIMEOUT,
    OLLAMA_TEMPERATURE,
)


class ResilientChatOllama(ChatOllama):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        parent = super()._generate
        return retry_ollama(
            lambda: parent(messages, stop=stop, run_manager=run_manager, **kwargs)
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        parent = super()._agenerate
        return await retry_ollama_async(
            lambda: parent(messages, stop=stop, run_manager=run_manager, **kwargs)
        )


_UNSET = object()


def chat_model(
    num_predict=1200, timeout=None, *, model=None, reasoning=_UNSET, temperature=None
):
    selected_reasoning = OLLAMA_REASONING if reasoning is _UNSET else reasoning
    return ResilientChatOllama(
        model=model or OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        num_ctx=OLLAMA_NUM_CTX,
        num_predict=num_predict
        if selected_reasoning is False
        else max(num_predict, 3200),
        temperature=OLLAMA_TEMPERATURE if temperature is None else temperature,
        reasoning=selected_reasoning,
        client_kwargs={
            "timeout": httpx.Timeout(timeout or OLLAMA_REQUEST_TIMEOUT, connect=10)
        },
    )
