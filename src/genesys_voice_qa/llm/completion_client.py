from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

ChatMessage = Mapping[str, Any]


@dataclass(frozen=True)
class CompletionParams:
    """Provider-agnostic chat completion request."""

    messages: Sequence[ChatMessage]
    temperature: float = 0.2
    max_completion_tokens: int | None = None
    json_mode: bool = False


class CompletionClient(ABC):
    """Abstract completion surface.

    Implementations live in sibling modules (Azure OpenAI, in-house gateway, etc.).
    Swap the concrete class in your composition root without changing analyzers.
    """

    @abstractmethod
    def complete(self, params: CompletionParams) -> str:
        """Return assistant message content (plain text or JSON when json_mode is true)."""
