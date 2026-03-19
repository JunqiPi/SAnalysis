"""
Base classes for team screeners.

Every team module inherits from BaseScreener, which enforces
the contract: fetch data -> analyze -> score -> return ScreenResults.
"""

from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Sequence

from src.core.config import get_config
from src.core.data_types import ScreenResult
from src.core.exceptions import TickerValidationError

logger = logging.getLogger(__name__)

# Valid ticker: 1-5 uppercase letters, optionally with a dot (BRK.B) or dash (BF-B)
_TICKER_RE = re.compile(r'^[A-Z]{1,5}(?:[.\-][A-Z]{1,2})?$')


def validate_ticker(ticker: str) -> str:
    """Normalize and validate a ticker symbol.

    Returns the cleaned ticker or raises TickerValidationError.
    """
    cleaned = ticker.strip().upper()
    if not cleaned:
        raise TickerValidationError("Ticker symbol cannot be empty.")
    if not _TICKER_RE.match(cleaned):
        raise TickerValidationError(
            f"Invalid ticker symbol: '{ticker}'. "
            f"Expected 1-5 uppercase letters (e.g., 'GME', 'BRK.B')."
        )
    return cleaned


class BaseScreener(ABC):
    """Abstract base for all six team screeners.

    Subclasses must implement:
        - team_name (property)
        - fetch_candidates() -> list[str]   -- tickers passing initial filter
        - analyze(ticker) -> ScreenResult | None
    """

    def __init__(self) -> None:
        self.cfg = get_config()

    @property
    @abstractmethod
    def team_name(self) -> str:
        """Short identifier: 'red', 'orange', 'yellow', 'green', 'blue'."""
        ...

    @abstractmethod
    def fetch_candidates(self) -> list[str]:
        """Return a list of ticker symbols that pass the initial screen."""
        ...

    @abstractmethod
    def analyze(self, ticker: str) -> ScreenResult | None:
        """Deep-analyze a single ticker and return a scored result, or None if disqualified."""
        ...

    def run(self, tickers: Sequence[str] | None = None) -> list[ScreenResult]:
        """Execute the full screening pipeline.

        If *tickers* is provided, skip fetch_candidates() and analyze those directly.
        Returns results sorted by score descending.
        """
        t0 = time.monotonic()

        if tickers is None:
            logger.info("[%s] Fetching candidates...", self.team_name)
            tickers = self.fetch_candidates()
            logger.info("[%s] %d candidates found.", self.team_name, len(tickers))

        # Validate and deduplicate tickers
        seen: set[str] = set()
        valid_tickers: list[str] = []
        for t in tickers:
            try:
                clean = validate_ticker(t)
                if clean not in seen:
                    seen.add(clean)
                    valid_tickers.append(clean)
            except ValueError as exc:
                logger.warning("[%s] Skipping invalid ticker: %s", self.team_name, exc)

        results: list[ScreenResult] = []
        analyzed = 0
        for ticker in valid_tickers:
            try:
                result = self.analyze(ticker)
                analyzed += 1
                if result is not None:
                    results.append(result)
            except Exception:
                logger.exception("[%s] Failed to analyze %s", self.team_name, ticker)

        results.sort(key=lambda r: r.score, reverse=True)
        elapsed = time.monotonic() - t0
        logger.info(
            "[%s] Done: %d/%d tickers passed (%.1fs elapsed).",
            self.team_name, len(results), analyzed, elapsed,
        )
        return results
