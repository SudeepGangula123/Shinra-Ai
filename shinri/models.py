"""The shared contract. Field names here are the names every part must use."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Label = Literal[
    "supported",
    "contradicted",
    "old_or_out_of_context",
    "signs_of_editing",
    "possible_ai_generated",
    "not_enough_evidence",
]
LABELS = (
    "supported", "contradicted", "old_or_out_of_context",
    "signs_of_editing", "possible_ai_generated", "not_enough_evidence",
)
Status = Literal["received", "processing", "done", "failed"]
InputType = Literal["text", "link", "image", "video", "audio"]


class Signal(BaseModel):
    """One piece of evidence. strength: -1 = against the claim being true / authentic,
    +1 = for it, 0 = neutral. weight: fixed by the team, never by the LLM."""
    engine: Literal["claim", "media", "origin"]
    kind: str = Field(min_length=1, max_length=60)
    strength: float = Field(ge=-1.0, le=1.0)
    weight: float = Field(default=1.0, ge=0.0, le=10.0)
    summary: str = Field(default="", max_length=500)
    evidence: dict[str, Any] = Field(default_factory=dict)
    limitation: str = Field(default="", max_length=500)
    mock: bool = False


class Claim(BaseModel):
    id: str = "c1"
    text: str
    quote: str = ""
    numbers: list[dict[str, Any]] = Field(default_factory=list)


class EngineResult(BaseModel):
    """What /engines/claim, /engines/media and /engines/origin return."""
    signals: list[dict[str, Any]] = Field(default_factory=list)   # validated one by one
    claims: list[Claim] = Field(default_factory=list)
    language: Optional[str] = None
    transcript: Optional[str] = None
    notes: list[str] = Field(default_factory=list)
    mock: bool = False


class Verdict(BaseModel):
    label: Label
    confidence: float = Field(ge=0.0, le=1.0)
    topReasons: list[str] = Field(default_factory=list)
    contributions: list[dict[str, Any]] = Field(default_factory=list)
    byEngine: dict[str, float] = Field(default_factory=dict)


class Explanation(BaseModel):
    language: str = "en"
    text: str
    citations: list[str] = Field(default_factory=list)
    generatedBy: str = "template"


class VerdictResult(BaseModel):
    """What /engines/verdict returns (Part 2)."""
    verdict: Verdict
    explanation: Explanation
    mock: bool = False
