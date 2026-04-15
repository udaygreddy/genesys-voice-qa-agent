from __future__ import annotations

import json
from dataclasses import dataclass

from genesys_voice_qa.llm.completion_client import CompletionClient, CompletionParams
from genesys_voice_qa.models import CallQualityAnalysis


SYSTEM_PROMPT = """You analyze contact-center voice call transcripts (Genesys).
You cannot hear audio; infer only from words, disfluencies, overlaps, repeated clarifications,
and explicit statements about audio quality.

Flag:
- Headset / audio path problems: one-way audio, cutting out, robotic/TTS-like glitches described,
  constant "can you hear me", "you're breaking up", long silence then confusion, repeated digits
  due to audio issues, agent/customer asking to switch devices.
- Background noise problems: loud office, music, TV, dogs, children, traffic/sirens, echoey room,
  side conversations, keyboard clatter if described.

Return STRICT JSON matching this schema (no markdown, no prose outside JSON):
{
  "has_problem": boolean,
  "confidence": number between 0 and 1,
  "issues": [
    {
      "category": "headset" | "background_noise" | "other",
      "severity": "low" | "medium" | "high",
      "summary": string,
      "evidence": [string, ...]
    }
  ],
  "notes": string | null
}

If the transcript is too short or unrelated, set has_problem false, confidence low, issues []."""


@dataclass(frozen=True)
class CallQualityReport:
    conversation_id: str
    analysis: CallQualityAnalysis
    raw_model_output: str


class CallQualityAnalyzer:
    def __init__(self, completion: CompletionClient) -> None:
        self._completion = completion

    def analyze_transcript(
        self,
        *,
        conversation_id: str,
        transcript_text: str,
        extra_context: str | None = None,
    ) -> CallQualityReport:
        user_parts = [f"conversation_id: {conversation_id}", "transcript:", transcript_text]
        if extra_context:
            user_parts.append("extra_context:")
            user_parts.append(extra_context)

        params = CompletionParams(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(user_parts)},
            ],
            temperature=0.1,
            max_completion_tokens=800,
            json_mode=True,
        )
        raw = self._completion.complete(params)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Model output was not valid JSON.") from exc

        analysis = CallQualityAnalysis.model_validate(payload)
        return CallQualityReport(
            conversation_id=conversation_id,
            analysis=analysis,
            raw_model_output=raw,
        )
