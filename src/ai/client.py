"""Anthropic SDK wrapper for AI re-scoring.

Thread-safe singleton. Gracefully degrades when the ``anthropic`` package
is not installed or no API key is configured.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any

from src.core.config import get_config
from src.ai.data_types import AIRescoreResult
from src.ai.prompts import TEAM_SYSTEM_PROMPTS, build_user_message

logger = logging.getLogger(__name__)

# Guard optional dependency (same pattern as praw in yellow team)
try:
    import anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False


class AIClient:
    """Thread-safe singleton wrapper around the Anthropic Messages API.

    Usage::

        client = AIClient.instance()
        if client.is_available():
            results = client.rescore_batch("red", ticker_data)
    """

    _instance: AIClient | None = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self.cfg = get_config()
        self._api_key = self._resolve_api_key()
        self._client: Any = None
        self._disabled = False  # Set True on unrecoverable auth error
        self._availability_warned = False  # Suppress duplicate warnings

        if _HAS_ANTHROPIC and self._api_key:
            timeout_s = self.cfg.get_nested("ai_rescore", "timeout_seconds", default=60)
            self._client = anthropic.Anthropic(
                api_key=self._api_key,
                timeout=float(timeout_s),
            )

    @classmethod
    def instance(cls) -> AIClient:
        """Return the singleton AIClient (thread-safe)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (useful for testing)."""
        with cls._lock:
            cls._instance = None

    def is_available(self) -> bool:
        """Check whether AI re-scoring can actually run.

        Logs a warning on the first unavailability check only, to avoid
        flooding logs when called from both __init__ and rescore_batch.
        """
        if not _HAS_ANTHROPIC:
            if not self._availability_warned:
                logger.warning(
                    "anthropic package not installed. "
                    "Install with: pip install 'sanalysis[ai]' or pip install anthropic"
                )
                self._availability_warned = True
            return False
        if not self._api_key:
            if not self._availability_warned:
                logger.warning(
                    "No Anthropic API key configured. Set ANTHROPIC_API_KEY env var "
                    "or add anthropic_api_key to config/secrets.yaml under api_keys."
                )
                self._availability_warned = True
            return False
        if self._disabled:
            if not self._availability_warned:
                logger.warning("AI re-scoring disabled due to earlier authentication failure.")
                self._availability_warned = True
            return False
        return True

    def rescore_batch(
        self,
        team: str,
        ticker_data: list[dict[str, Any]],
    ) -> list[AIRescoreResult]:
        """Call Claude to re-score a batch of tickers for one team.

        Args:
            team: Team color key (e.g. "red").
            ticker_data: List of dicts with keys: ticker, quant_score, signals, metadata.

        Returns:
            List of AIRescoreResult. Empty list on any unrecoverable failure.
        """
        if not self.is_available() or not ticker_data:
            return []

        system_prompt = TEAM_SYSTEM_PROMPTS.get(team)
        if not system_prompt:
            logger.error("No system prompt defined for team '%s'.", team)
            return []

        user_message = build_user_message(team, ticker_data)
        model = self.cfg.get_nested("ai_rescore", "model", default="claude-opus-4-6")
        max_tokens = self.cfg.get_nested("ai_rescore", "max_tokens", default=4096)
        temperature = self.cfg.get_nested("ai_rescore", "temperature", default=0.3)
        max_retries = self.cfg.get_nested("ai_rescore", "max_retries", default=3)

        raw_text = self._call_api(
            model=model,
            system=system_prompt,
            user_message=user_message,
            max_tokens=max_tokens,
            temperature=temperature,
            max_retries=max_retries,
        )

        if raw_text is None:
            return []

        return self._parse_response(raw_text, team, ticker_data)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_api_key(self) -> str:
        """Resolve API key: env var first, then config."""
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if key:
            return key
        return self.cfg.get_nested("api_keys", "anthropic_api_key", default="") or ""

    def _call_api(
        self,
        model: str,
        system: str,
        user_message: str,
        max_tokens: int,
        temperature: float,
        max_retries: int,
    ) -> str | None:
        """Call Anthropic Messages API with retry logic.

        Returns the response text, or None on unrecoverable failure.
        """
        for attempt in range(1, max_retries + 1):
            try:
                response = self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": user_message}],
                )
                # Extract text from response
                text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text += block.text
                return text

            except anthropic.AuthenticationError as exc:
                logger.error(
                    "Anthropic API authentication failed (invalid key). "
                    "AI re-scoring disabled for this run. Error: %s", exc
                )
                self._disabled = True
                return None

            except anthropic.RateLimitError as exc:
                if attempt >= max_retries:
                    logger.error(
                        "Rate limited by Anthropic API after %d attempts. "
                        "Skipping AI re-scoring. Error: %s",
                        max_retries, exc,
                    )
                    return None
                wait = 2 ** attempt
                logger.warning(
                    "Rate limited by Anthropic API (attempt %d/%d). "
                    "Retrying in %ds. Error: %s",
                    attempt, max_retries, wait, exc,
                )
                time.sleep(wait)

            except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                wait = 2 ** attempt
                if attempt < max_retries:
                    logger.warning(
                        "Anthropic API error (attempt %d/%d). "
                        "Retrying in %ds. Error: %s",
                        attempt, max_retries, wait, exc,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "Anthropic API failed after %d attempts. "
                        "Skipping AI re-scoring. Error: %s",
                        max_retries, exc,
                    )
                    return None

            except Exception as exc:
                logger.error(
                    "Unexpected error calling Anthropic API: %s", exc,
                    exc_info=True,
                )
                return None

        return None

    def _parse_response(
        self,
        raw_text: str,
        team: str,
        ticker_data: list[dict[str, Any]],
    ) -> list[AIRescoreResult]:
        """Parse Claude's JSON response into AIRescoreResult objects.

        Handles markdown code fences, validates structure, and clamps scores.
        """
        # Build quant_score lookup
        quant_lookup = {td["ticker"]: td.get("quant_score", 0) for td in ticker_data}
        ai_weight = self.cfg.get_nested("ai_rescore", "ai_weight", default=0.3)

        # Strip markdown code fences if present
        text = raw_text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse AI response as JSON for team '%s': %s\nRaw: %.500s",
                team, exc, raw_text,
            )
            return []

        if not isinstance(parsed, list):
            logger.error(
                "AI response for team '%s' is not a JSON array. Got: %s",
                team, type(parsed).__name__,
            )
            return []

        results = []
        for item in parsed:
            if not isinstance(item, dict):
                continue

            ticker = item.get("ticker", "")
            if not ticker:
                continue

            # Clamp ai_score to [0, 100]
            raw_score = item.get("ai_score", 50)
            try:
                ai_score = float(raw_score)
            except (ValueError, TypeError):
                ai_score = 50.0

            if ai_score < 0 or ai_score > 100:
                logger.warning(
                    "AI score for %s/%s out of range (%.1f), clamping to [0,100].",
                    team, ticker, ai_score,
                )
                ai_score = max(0.0, min(100.0, ai_score))

            quant_score = quant_lookup.get(ticker, 0)
            blended = quant_score * (1 - ai_weight) + ai_score * ai_weight

            confidence = item.get("ai_confidence", "medium")
            if confidence not in ("high", "medium", "low"):
                confidence = "medium"

            results.append(AIRescoreResult(
                ticker=ticker,
                team=team,
                ai_score=ai_score,
                ai_confidence=confidence,
                ai_reasoning=str(item.get("ai_reasoning", "")),
                ai_flags=item.get("ai_flags", []) if isinstance(item.get("ai_flags"), list) else [],
                quant_score=quant_score,
                blended_score=blended,
            ))

        return results
