from __future__ import annotations

from openai import AzureOpenAI

from genesys_voice_qa.llm.completion_client import CompletionClient, CompletionParams


class AzureOpenAICompletionClient(CompletionClient):
    """Azure OpenAI chat completions."""

    def __init__(
        self,
        *,
        azure_endpoint: str,
        api_key: str,
        api_version: str,
        deployment: str,
    ) -> None:
        self._deployment = deployment
        self._client = AzureOpenAI(
            azure_endpoint=azure_endpoint.rstrip("/"),
            api_key=api_key,
            api_version=api_version,
        )

    def complete(self, params: CompletionParams) -> str:
        kwargs: dict = {
            "model": self._deployment,
            "messages": list(params.messages),
            "temperature": params.temperature,
        }
        if params.max_completion_tokens is not None:
            kwargs["max_completion_tokens"] = params.max_completion_tokens
        if params.json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("Azure OpenAI returned empty assistant content.")
        return content
