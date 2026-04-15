from __future__ import annotations

import os

from genesys_voice_qa.llm.azure_openai_completion import AzureOpenAICompletionClient
from genesys_voice_qa.llm.completion_client import CompletionClient
from genesys_voice_qa.llm.in_house_gateway_completion import InHouseGatewayCompletionClient


def completion_client_from_env() -> CompletionClient:
    """Select completion backend from environment variables.

    Set ``LLM_BACKEND=azure`` (default) or ``LLM_BACKEND=gateway``.

    Azure:
      AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_DEPLOYMENT

    Gateway:
      AI_GATEWAY_BASE_URL, optional AI_GATEWAY_API_KEY, optional AI_GATEWAY_MODEL
    """

    backend = os.getenv("LLM_BACKEND", "azure").strip().lower()
    if backend == "gateway":
        base_url = os.environ["AI_GATEWAY_BASE_URL"]
        return InHouseGatewayCompletionClient(
            base_url=base_url,
            api_key=os.getenv("AI_GATEWAY_API_KEY"),
            model=os.getenv("AI_GATEWAY_MODEL"),
        )

    return AzureOpenAICompletionClient(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    )
