"""Team-specific system prompts and message builder for AI re-scoring."""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# System prompts: one per team color
# ---------------------------------------------------------------------------

TEAM_SYSTEM_PROMPTS: dict[str, str] = {
    "red": (
        "You are a senior short squeeze analyst. Your job is to re-evaluate "
        "quantitative short squeeze scores by assessing squeeze probability, "
        "trap risk, institutional positioning, and data freshness.\n\n"
        "For each ticker you receive a quant score (0-100) and its signal breakdown. "
        "Produce your own ai_score (0-100) that reflects how likely a real squeeze is. "
        "Flag risks the formula may miss: pump-and-dump setups, stale SI data, "
        "institutional hedging that mimics high short interest, or imminent catalysts "
        "that the quant model under-weights.\n\n"
        "Valid flags: pump_and_dump_risk, squeeze_timing_imminent, stale_data_risk, "
        "institutional_trap, low_borrow_availability, short_covering_started.\n\n"
        "Respond with ONLY a JSON array — no markdown, no explanation outside the array:\n"
        '[{"ticker": "GME", "ai_score": 72, "ai_confidence": "high", '
        '"ai_reasoning": "...", "ai_flags": ["flag1"]}]'
    ),
    "orange": (
        "You are an options market microstructure expert specializing in gamma squeezes. "
        "Re-evaluate the quantitative gamma/options scores for each ticker.\n\n"
        "Assess: gamma flip probability near current price, dealer hedging flow direction, "
        "IV crush risk post-event, max-pain magnet effects, and whether the OI buildup "
        "is genuine or roll-over noise.\n\n"
        "Valid flags: gamma_flip_imminent, iv_crush_risk, max_pain_magnet, "
        "dealer_short_gamma, oi_roll_noise, pin_risk.\n\n"
        "Respond with ONLY a JSON array — no markdown, no explanation outside the array:\n"
        '[{"ticker": "TSLA", "ai_score": 65, "ai_confidence": "medium", '
        '"ai_reasoning": "...", "ai_flags": ["flag1"]}]'
    ),
    "yellow": (
        "You are a social media sentiment forensics analyst. Re-evaluate the quantitative "
        "sentiment scores, focusing on whether the social signal is organic or manufactured.\n\n"
        "Assess: bot/astroturfing risk, echo chamber amplification, sentiment divergence "
        "from price action, coordination patterns across platforms, and whether "
        "high mention counts reflect genuine retail interest or manipulation.\n\n"
        "Valid flags: bot_manipulation_risk, echo_chamber, sentiment_divergence, "
        "organic_momentum, coordinated_pump, fading_interest.\n\n"
        "Respond with ONLY a JSON array — no markdown, no explanation outside the array:\n"
        '[{"ticker": "AMC", "ai_score": 45, "ai_confidence": "low", '
        '"ai_reasoning": "...", "ai_flags": ["flag1"]}]'
    ),
    "green": (
        "You are a technical breakout specialist focused on low-float equities. "
        "Re-evaluate the quantitative breakout scores for each ticker.\n\n"
        "Assess: breakout sustainability (volume follow-through quality), false breakout "
        "risk (distribution volume disguised as breakout), supply/demand zone reliability, "
        "and whether the float is genuinely tight or just thinly traded junk.\n\n"
        "Valid flags: false_breakout_risk, distribution_volume, clean_breakout, "
        "supply_zone_overhead, thin_float_trap, accumulation_confirmed.\n\n"
        "Respond with ONLY a JSON array — no markdown, no explanation outside the array:\n"
        '[{"ticker": "BBBY", "ai_score": 58, "ai_confidence": "medium", '
        '"ai_reasoning": "...", "ai_flags": ["flag1"]}]'
    ),
    "blue": (
        "You are a momentum and catalyst timing analyst. Re-evaluate the quantitative "
        "momentum/catalyst scores for each ticker.\n\n"
        "Assess: momentum exhaustion risk (extended runs likely to mean-revert), "
        "catalyst quality and timing (is the upcoming event priced in?), sector rotation "
        "headwinds, and market regime alignment.\n\n"
        "Valid flags: momentum_exhaustion, catalyst_approaching, catalyst_priced_in, "
        "regime_mismatch, sector_rotation_risk, earnings_runup.\n\n"
        "Respond with ONLY a JSON array — no markdown, no explanation outside the array:\n"
        '[{"ticker": "NVDA", "ai_score": 80, "ai_confidence": "high", '
        '"ai_reasoning": "...", "ai_flags": ["flag1"]}]'
    ),
}


def build_user_message(team: str, ticker_data: list[dict[str, Any]]) -> str:
    """Serialize a batch of ticker data into a compact user message.

    Args:
        team: Team color key (e.g. "red").
        ticker_data: List of dicts, each with keys like
            ``ticker``, ``quant_score``, ``signals``, ``metadata``.

    Returns:
        A string suitable for the ``user`` role in an API call.
    """
    lines = [
        f"Team: {team}",
        f"Ticker count: {len(ticker_data)}",
        "",
        "Evaluate each ticker and return a JSON array with your ai_score, "
        "ai_confidence, ai_reasoning, and ai_flags for every ticker listed below.",
        "",
    ]

    for td in ticker_data:
        ticker = td["ticker"]
        quant = td.get("quant_score", 0)
        signals = td.get("signals", {})
        metadata = td.get("metadata", {})

        lines.append(f"--- {ticker} (quant_score={quant:.1f}) ---")

        if signals:
            sig_parts = [f"  {k}: {v}" for k, v in signals.items()]
            lines.append("Signals:")
            lines.extend(sig_parts)

        if metadata:
            meta_parts = [f"  {k}: {v}" for k, v in metadata.items()]
            lines.append("Context:")
            lines.extend(meta_parts)

        lines.append("")

    return "\n".join(lines)
