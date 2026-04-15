from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class QualityIssue(BaseModel):
    category: Literal["headset", "background_noise", "other"]
    severity: Literal["low", "medium", "high"]
    summary: str = Field(description="Short operator-facing summary.")
    evidence: list[str] = Field(
        default_factory=list,
        description="Quoted snippets or paraphrases from the transcript that support the finding.",
    )


class CallQualityAnalysis(BaseModel):
    has_problem: bool
    confidence: float = Field(ge=0.0, le=1.0)
    issues: list[QualityIssue] = Field(default_factory=list)
    notes: str | None = Field(
        default=None,
        description="Optional caveats, e.g. transcript-only limitations.",
    )
