from __future__ import annotations

import json
from typing import Any

import httpx

from genesys_voice_qa.llm.completion_client import CompletionClient, CompletionParams


class InHouseGatewayCompletionClient(CompletionClient):
    """Drop-in replacement for :class:`AzureOpenAICompletionClient` that calls your AI gateway.

    Replace this module (or adjust ``base_url`` / payload mapping) to match your
    internal gateway contract while keeping :class:`CompletionClient` stable for the rest
    of the codebase.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        model: str | None = None,
        timeout_s: float = 60.0,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_s
        self._extra_headers = extra_headers or {}

    def complete(self, params: CompletionParams) -> str:
        headers: dict[str, str] = {"Content-Type": "application/json", **self._extra_headers}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        body: dict[str, Any] = {
            "messages": list(params.messages),
            "temperature": params.temperature,
        }
        if self._model:
            body["model"] = self._model
        if params.max_completion_tokens is not None:
            body["max_completion_tokens"] = params.max_completion_tokens
        if params.json_mode:
            body["response_format"] = {"type": "json_object"}

        url = f"{self._base_url}/v1/chat/completions"
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(url, headers=headers, content=json.dumps(body))
            response.raise_for_status()
            payload = response.json()

        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("Gateway response missing choices.")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content:
            raise RuntimeError("Gateway returned empty assistant content.")
        return content
