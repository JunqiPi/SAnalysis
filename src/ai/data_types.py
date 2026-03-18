"""Data types for AI re-scoring results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AIRescoreResult:
    """A single ticker's AI re-evaluation for one team."""
    ticker: str
    team: str
    ai_score: float              # 0-100, AI's assessment
    ai_confidence: str           # "high" | "medium" | "low"
    ai_reasoning: str            # Free-text explanation
    ai_flags: list[str] = field(default_factory=list)
    quant_score: float = 0.0     # Original quantitative score
    blended_score: float = 0.0   # Weighted blend of quant + AI
