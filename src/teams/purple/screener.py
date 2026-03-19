"""
Purple Team: 10x Potential Assessor

Evaluates whether a stock has the STRUCTURAL characteristics to achieve
10x+ returns.  Unlike other teams that focus on specific catalysts
(short squeeze, gamma, sentiment, breakout, momentum), Purple asks:
"If everything aligns, does this stock have the *capacity* for a 10-bagger?"

Phase 1 data sources:
  - Finviz free-tier (small-cap screening)
  - yfinance (fundamentals, OHLCV, 52-week ranges, insider/institution data)
  - pandas_ta / manual (Bollinger Bands, OBV)

Scoring model (0-100):
  - Market Cap Tier     (0-25): Smaller cap = more explosive upside
  - Float Structure     (0-25): Float tightness + insider alignment
  - Dilution Risk       (0-25): Inverted — low dilution risk = high score
  - Explosive Setup     (0-25): Technical coiling & accumulation patterns
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from src.core.base import BaseScreener
from src.core.data_types import ScreenResult
from src.utils import finviz_scraper, market_data, technical

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Market cap piecewise breakpoints: (upper_bound_millions, score)
# Ordered ascending so the first match wins.
# ---------------------------------------------------------------------------
_MCAP_BREAKPOINTS: list[tuple[float, float]] = [
    (50.0, 25.0),     # nano cap
    (300.0, 21.0),    # micro cap
    (500.0, 17.0),    # small micro
    (1_000.0, 13.0),  # small cap
    (2_000.0, 8.0),   # small-mid
    (5_000.0, 3.0),   # mid cap
]
_MCAP_LARGE_SCORE = 0.0  # >= $5B

# ---------------------------------------------------------------------------
# Float size breakpoints: (upper_bound_shares_millions, score)
# ---------------------------------------------------------------------------
_FLOAT_BREAKPOINTS: list[tuple[float, float]] = [
    (5.0, 10.0),
    (10.0, 8.0),
    (20.0, 6.0),
    (50.0, 4.0),
    (100.0, 2.0),
]

# ---------------------------------------------------------------------------
# 52-week range position -> score mapping
# Position = (price - 52w_low) / (52w_high - 52w_low)
# ---------------------------------------------------------------------------
_52W_SCORE_MAP: list[tuple[tuple[float, float], float]] = [
    ((0.1, 0.3), 6.0),   # near 52w low but bouncing = max upside
    ((0.3, 0.5), 4.0),
    ((0.0, 0.1), 2.0),   # still falling, risky
    ((0.8, 1.01), 3.0),  # already extended but could breakout further
    ((0.5, 0.8), 1.0),
]


class TenBaggerScreener(BaseScreener):
    """Purple Team screener: identifies stocks with structural 10x potential.

    Focuses on the *capacity* for explosive returns by evaluating:
    - Market cap tier (smaller = more room to grow)
    - Float structure (tight float + insider alignment)
    - Dilution risk (healthy balance sheet = sustainable move)
    - Explosive setup (volatility compression + accumulation)
    """

    @property
    def team_name(self) -> str:
        return "purple"

    def _team_cfg(self) -> dict[str, Any]:
        """Return the purple_team config section, defaulting to empty dict.

        Unlike the original 5 teams whose config sections always exist in
        ``default.yaml``, Purple is a new addition and the user may not
        have added a ``purple_team`` section yet.  Returning ``{}``
        allows all ``.get()`` calls to fall through to their defaults.
        """
        return self.cfg.data.get("purple_team", {})

    # ------------------------------------------------------------------
    # Candidate discovery
    # ------------------------------------------------------------------

    _FALLBACK_TICKERS: list[str] = [
        "FFIE", "MULN", "ATER", "CLOV", "GOEV", "FUBO", "SOFI",
        "MARA", "RIOT", "SNDL", "TLRY", "PROG", "ISPC", "BFRI",
        "IRNT", "CEI", "NILE", "PIXY", "RKT", "WKHS", "SPCE",
    ]

    def fetch_candidates(self) -> list[str]:
        """Fetch small-cap candidates from Finviz with fallback list.

        Primary filters:
          - Market cap under $2B (``cap_smallunder``)
          - Average volume > 200K (``sh_avgvol_o200``)
          - Price > $1 (``sh_price_o1``)

        If Finviz fails or returns empty, falls back to a curated list
        of historically volatile micro/small-cap stocks.
        """
        try:
            df = finviz_scraper.screen(
                [
                    "cap_smallunder",
                    "sh_avgvol_o200",
                    "sh_price_o1",
                ],
                order_by=finviz_scraper.ORDER_MARKET_CAP_ASC,
                view=finviz_scraper.VIEW_OVERVIEW,
            )
            # Client-side sort: smallest market cap first (10x potential)
            df = finviz_scraper.sort_dataframe(df, "Market Cap", ascending=True)
            if not df.empty:
                ticker_col = "Ticker" if "Ticker" in df.columns else df.columns[1]
                tickers = df[ticker_col].tolist()
                logger.info(
                    "[purple] Finviz returned %d small-cap candidates.", len(tickers),
                )
                return tickers
            logger.warning("[purple] Finviz returned empty results; using fallback list.")
        except Exception:
            logger.exception("[purple] Finviz scan failed; using fallback list.")

        return list(self._FALLBACK_TICKERS)

    # ------------------------------------------------------------------
    # Factor 1: Market Cap Tier (0-25)
    # ------------------------------------------------------------------

    def _score_market_cap_tier(self, info: dict[str, Any]) -> float:
        """Score 0-25: Smaller market cap = more explosive upside potential.

        Uses piecewise breakpoints defined in ``_MCAP_BREAKPOINTS``.
        Unknown market cap receives a conservative 5 points.
        """
        mcap = info.get("marketCap")
        if mcap is None:
            return 5.0

        mcap_m = mcap / 1e6
        for upper_bound, score in _MCAP_BREAKPOINTS:
            if mcap_m < upper_bound:
                return score
        return _MCAP_LARGE_SCORE

    # ------------------------------------------------------------------
    # Factor 2: Float Structure (0-25)
    # ------------------------------------------------------------------

    def _score_float_structure(self, info: dict[str, Any]) -> float:
        """Score 0-25: Float tightness + insider alignment + low institutional.

        Sub-scores:
          a) Float size (0-10): smaller float = more explosive
          b) Insider ownership (0-8): higher insider % = better alignment
          c) Institutional ownership (0-7): LOWER is better for squeeze potential
        """
        score = 0.0

        # --- (a) Float size ---
        float_shares = info.get("floatShares")
        if float_shares is not None and float_shares > 0:
            flt_m = float_shares / 1e6
            sub_a = 0.0
            for upper_bound, pts in _FLOAT_BREAKPOINTS:
                if flt_m < upper_bound:
                    sub_a = pts
                    break
            # flt_m >= 100M falls through with sub_a = 0.0
            score += sub_a
        # float_shares is None or 0 -> 0 pts (no evidence of tight float)

        # --- (b) Insider ownership (yfinance returns decimal, e.g. 0.30 = 30%) ---
        insider_pct = info.get("heldPercentInsiders")
        if insider_pct is not None:
            if insider_pct >= 0.30:
                score += 8.0
            elif insider_pct >= 0.20:
                score += 6.0
            elif insider_pct >= 0.10:
                score += 4.0
            elif insider_pct >= 0.05:
                score += 2.0
            # <5% -> 0
        # None -> 0

        # --- (c) Institutional ownership (lower = more retail-driven potential) ---
        inst_pct = info.get("heldPercentInstitutions")
        if inst_pct is not None:
            if inst_pct < 0.20:
                score += 7.0
            elif inst_pct < 0.40:
                score += 5.0
            elif inst_pct < 0.60:
                score += 3.0
            else:
                score += 1.0
        # None -> 0

        return min(25.0, score)

    # ------------------------------------------------------------------
    # Factor 3: Dilution Risk (0-25, inverted: low risk = high score)
    # ------------------------------------------------------------------

    def _score_dilution_risk(self, info: dict[str, Any]) -> float:
        """Score 0-25: Low dilution risk = high score (inverted risk metric).

        Sub-scores:
          a) Cash position health (0-10): cash vs. debt ratio
          b) Cash flow sustainability (0-8): OCF/FCF positivity
          c) Share structure tightness (0-7): float/outstanding ratio
        """
        score = 0.0

        # --- (a) Cash position health ---
        total_cash = info.get("totalCash")
        total_debt = info.get("totalDebt")

        if total_cash is not None and total_debt is not None:
            # Both available — compare directly
            if total_debt <= 0:
                # No debt at all -> fortress
                score += 10.0 if (total_cash or 0) > 0 else 7.0
            elif total_cash > total_debt * 2:
                score += 10.0
            elif total_cash > total_debt:
                score += 7.0
            elif total_cash > total_debt * 0.5:
                score += 4.0
            else:
                score += 1.0  # Heavy debt
        else:
            score += 3.0  # Conservative default when data unavailable

        # --- (b) Cash flow sustainability ---
        ocf = info.get("operatingCashflow")
        fcf = info.get("freeCashflow")

        if ocf is not None:
            if ocf > 0:
                score += 8.0  # Self-funding, no need to dilute
            elif fcf is not None and fcf > 0:
                # OCF negative but FCF positive (unusual but possible
                # with large working capital swings)
                score += 4.0
            else:
                # Both negative — check if there is a reasonable cash runway.
                # Simplified: if they have substantial cash relative to burn,
                # give partial credit.  Full cash-runway calc would require
                # quarterly data which yfinance info dict doesn't provide
                # reliably, so we use a heuristic.
                if total_cash is not None and ocf is not None and ocf < 0:
                    runway_months = (total_cash / abs(ocf)) * 12 if ocf != 0 else 0
                    if runway_months > 12:
                        score += 2.0
                    # else: 0 (heavy burn)
                # else: 0
        else:
            score += 2.0  # Conservative default

        # --- (c) Share structure tightness ---
        float_shares = info.get("floatShares")
        shares_out = info.get("sharesOutstanding")

        if float_shares is not None and shares_out is not None and shares_out > 0:
            ratio = float_shares / shares_out
            if ratio < 0.5:
                score += 7.0  # Many locked shares, low dilution risk from float
            elif ratio <= 0.8:
                score += 5.0  # Moderate lockup
            else:
                score += 2.0  # Most shares already floating
        else:
            score += 3.0  # Conservative default

        return min(25.0, score)

    # ------------------------------------------------------------------
    # Factor 4: Explosive Setup (0-25)
    # ------------------------------------------------------------------

    def _score_explosive_setup(
        self,
        ticker: str,
        info: dict[str, Any],
        hist: pd.DataFrame,
    ) -> float:
        """Score 0-25: Technical coiling & accumulation patterns.

        Sub-scores:
          a) Bollinger Band squeeze / volatility compression (0-8)
          b) 52-week range position (0-6)
          c) OBV divergence / accumulation (0-6)
          d) Recent price action momentum — 5-day return (0-5)

        Args:
            ticker: Symbol (for logging).
            info: yfinance info dict (52w high/low).
            hist: 6mo daily OHLCV history (min 20 rows guaranteed by caller).
        """
        score = 0.0
        close = hist["Close"]

        # --- (a) Bollinger Band squeeze / volatility compression ---
        score += self._subscore_bb_squeeze(close)

        # --- (b) 52-week range position ---
        current_price = float(close.iloc[-1])
        score += self._subscore_52w_position(info, current_price)

        # --- (c) OBV divergence / accumulation ---
        score += self._subscore_obv_trend(hist)

        # --- (d) Recent price action momentum (5-day return) ---
        score += self._subscore_recent_momentum(close)

        return min(25.0, score)

    @staticmethod
    def _subscore_bb_squeeze(close: pd.Series) -> float:
        """Bollinger Band width compression relative to its 20-day average.

        Extreme compression (current width < 50% of avg) signals a "coiling"
        pattern that often precedes a large directional move.

        Returns 0-8 points.
        """
        if len(close) < 30:
            # Need enough data for BB(20) + 20-day SMA of BB width
            return 1.0

        bb_upper, bb_mid, bb_lower = technical.bollinger_bands(close, period=20, std_dev=2.0)

        # BB width as fraction of midline (avoids absolute dollar comparisons)
        bb_width = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)
        bb_width = bb_width.dropna()

        if len(bb_width) < 20:
            return 1.0

        current_width = bb_width.iloc[-1]
        avg_width = bb_width.iloc[-20:].mean()

        if pd.isna(current_width) or pd.isna(avg_width) or avg_width <= 0:
            return 1.0

        ratio = current_width / avg_width

        if ratio < 0.5:
            return 8.0   # Extreme compression
        if ratio < 0.7:
            return 5.0
        if ratio < 0.9:
            return 3.0
        return 1.0       # Expanding or normal

    @staticmethod
    def _subscore_52w_position(info: dict[str, Any], price: float) -> float:
        """Score based on where current price sits in the 52-week range.

        The sweet spot for 10x potential is 10-30% from the 52-week low
        (bottomed out and beginning to recover), providing maximum upside
        headroom.

        Returns 0-6 points.
        """
        high_52w = info.get("fiftyTwoWeekHigh")
        low_52w = info.get("fiftyTwoWeekLow")

        if high_52w is None or low_52w is None:
            return 2.0  # Conservative default

        range_52w = high_52w - low_52w
        if range_52w <= 0:
            return 2.0  # Degenerate range (high == low or bad data)

        position = (price - low_52w) / range_52w
        # Clamp to [0, 1] in case price is outside the stored 52w range
        # (yfinance updates these with a slight lag)
        position = max(0.0, min(1.0, position))

        for (lo, hi), pts in _52W_SCORE_MAP:
            if lo <= position < hi:
                return pts

        return 1.0  # Fallback (should not be reached given the map covers [0, 1])

    @staticmethod
    def _subscore_obv_trend(hist: pd.DataFrame) -> float:
        """Detect OBV divergence / accumulation over the last 10 days.

        OBV rising while price is flat or declining is a classic
        accumulation signal — "smart money" buying before a move.

        Returns 0-6 points.
        """
        if len(hist) < 10:
            return 0.0

        recent = hist.tail(10)
        obv_vals = technical.obv(recent["Close"], recent["Volume"])

        if obv_vals.empty or len(obv_vals) < 2:
            return 0.0

        obv_start = obv_vals.iloc[0]
        obv_end = obv_vals.iloc[-1]

        if pd.isna(obv_start) or pd.isna(obv_end):
            return 0.0

        obv_delta = obv_end - obv_start

        price_start = float(recent["Close"].iloc[0])
        price_end = float(recent["Close"].iloc[-1])
        if price_start <= 0:
            return 0.0

        price_change_pct = (price_end - price_start) / price_start * 100

        if obv_delta > 0 and price_change_pct <= 0:
            return 6.0  # Bullish divergence: accumulation while price flat/down
        if obv_delta > 0 and price_change_pct > 0:
            return 4.0  # Confirmed uptrend
        if abs(obv_delta) < 1:
            # OBV essentially flat — use a small tolerance rather than
            # exact zero, since cumsum rarely lands on precisely 0
            return 2.0
        return 0.0  # OBV declining

    @staticmethod
    def _subscore_recent_momentum(close: pd.Series) -> float:
        """5-day price return scoring.

        A moderate positive return (5-30%) indicates building momentum
        without exhaustion.  Returns above 30% are flagged as potentially
        overextended (lower score).

        Returns 0-5 points.
        """
        if len(close) < 6:
            return 0.0

        price_now = float(close.iloc[-1])
        price_5d_ago = float(close.iloc[-6])  # -6 because iloc is 0-indexed

        if price_5d_ago <= 0:
            return 0.0

        ret_pct = (price_now / price_5d_ago - 1) * 100

        if 5.0 <= ret_pct <= 30.0:
            return 5.0   # Strong but not exhausted
        if 0.0 <= ret_pct < 5.0:
            return 3.0
        if -10.0 <= ret_pct < 0.0:
            return 2.0   # Could bounce
        if ret_pct > 30.0:
            return 1.0   # Possibly overextended
        return 0.0        # Deep decline (< -10%)

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    def analyze(self, ticker: str) -> ScreenResult | None:
        """Full analysis pipeline for a single ticker.

        1. Fetch info + enforce hard market cap gate
        2. Fetch 6mo history (single call, reused by all sub-scores)
        3. Score four factors
        4. Return ScreenResult with signals and metadata
        """
        info = market_data.get_ticker_info(ticker)
        if not info:
            logger.debug("[purple] %s: no info data available, skipping.", ticker)
            return None

        # Hard market cap gate
        mcap = info.get("marketCap")
        cfg = self._team_cfg()
        max_mcap = cfg.get("max_market_cap_millions", 2000)
        if mcap is not None and mcap > max_mcap * 1e6:
            logger.debug(
                "[purple] %s market cap $%.1fM exceeds max $%.1fM, skipping.",
                ticker, mcap / 1e6, float(max_mcap),
            )
            return None

        # Fetch 6mo history ONCE
        hist = market_data.get_history(ticker, period="6mo", interval="1d")
        if hist.empty or len(hist) < 20:
            logger.debug(
                "[purple] %s: insufficient history (%d bars), skipping.",
                ticker, len(hist),
            )
            return None

        # Score four factors
        s1 = self._score_market_cap_tier(info)
        s2 = self._score_float_structure(info)
        s3 = self._score_dilution_risk(info)
        s4 = self._score_explosive_setup(ticker, info, hist)
        total = s1 + s2 + s3 + s4

        float_shares = info.get("floatShares")
        insider_pct = info.get("heldPercentInsiders")
        inst_pct = info.get("heldPercentInstitutions")

        return ScreenResult(
            ticker=ticker,
            team="purple",
            score=total,
            signals={
                "market_cap_tier": s1,
                "float_structure": s2,
                "dilution_risk": s3,
                "explosive_setup": s4,
                "float_shares_millions": (float_shares or 0) / 1e6,
                "insider_pct": (insider_pct or 0) * 100,
                "institutional_pct": (inst_pct or 0) * 100,
            },
            metadata={
                "market_cap_millions": mcap / 1e6 if mcap else None,
                "float_shares": float_shares,
                "shares_outstanding": info.get("sharesOutstanding"),
                "insider_pct": insider_pct,
                "institutional_pct": inst_pct,
                "total_cash": info.get("totalCash"),
                "total_debt": info.get("totalDebt"),
                "operating_cashflow": info.get("operatingCashflow"),
                "free_cashflow": info.get("freeCashflow"),
                "high_52w": info.get("fiftyTwoWeekHigh"),
                "low_52w": info.get("fiftyTwoWeekLow"),
            },
        )
