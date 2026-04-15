from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GenesysCallContext:
    """Minimal Genesys Cloud context you typically receive from webhooks or async jobs."""

    conversation_id: str
    communication_id: str | None = None
    queue_id: str | None = None
    participant_id: str | None = None
    direction: str | None = None
    raw_event: dict[str, Any] | None = None


def format_genesys_context_block(ctx: GenesysCallContext) -> str:
    lines = [
        f"conversation_id={ctx.conversation_id}",
    ]
    if ctx.communication_id:
        lines.append(f"communication_id={ctx.communication_id}")
    if ctx.queue_id:
        lines.append(f"queue_id={ctx.queue_id}")
    if ctx.participant_id:
        lines.append(f"participant_id={ctx.participant_id}")
    if ctx.direction:
        lines.append(f"direction={ctx.direction}")
    return "\n".join(lines)


def extract_transcript_text(payload: dict[str, Any]) -> str | None:
    """Best-effort helper when transcript text is nested differently per integration.

    Point this at the JSON body you receive from:
    - a Genesys Cloud Data Action / webhook you configure, or
    - an intermediate service that already normalized transcripts.
    """

    for key in ("transcript", "transcriptText", "text", "utterances"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    utterances = payload.get("utterances")
    if isinstance(utterances, list):
        parts: list[str] = []
        for item in utterances:
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("transcript")
            role = item.get("participantType") or item.get("role") or "speaker"
            if isinstance(text, str) and text.strip():
                parts.append(f"{role}: {text}")
        if parts:
            return "\n".join(parts)
    return None
