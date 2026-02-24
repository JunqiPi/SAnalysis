"""
Red Team: Short Squeeze Sniper Screener

Phase 1 data sources:
  - Finviz free-tier (short float screening)
  - yfinance (short interest, float, DTC, fundamentals)
  - FINRA official data (future: manual import)

Scoring model (0-100):
  - Short Intensity     (0-25): Short float %, shares short trend
  - Cover Difficulty    (0-25): Days to cover, borrow fee proxy, float tightness
  - Catalyst Proximity  (0-25): Earnings proximity, social buzz, unusual volume
  - Technical Momentum  (0-25): RSI, price vs MAs, recent returns
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from src.core.base import BaseScreener
from src.core.data_types import ScreenResult, ShortData
from src.utils import finviz_scraper, market_data, technical

logger = logging.getLogger(__name__)


class ShortSqueezeScreener(BaseScreener):
    """Red Team screener: identifies potential short squeeze candidates."""

    @property
    def team_name(self) -> str:
        return "red"

    def _team_cfg(self):
        return self.cfg["red_team"]

    # ------------------------------------------------------------------
    # Phase 1: Candidate discovery
    # ------------------------------------------------------------------

    def fetch_candidates(self) -> list[str]:
        """Fetch initial candidate tickers from Finviz + yfinance fallback."""
        cfg = self._team_cfg()
        finviz_cfg = cfg.get("finviz_filters", {})

        # Primary: Finviz screener
        try:
            df = finviz_scraper.get_short_squeeze_candidates(
                min_short_float=finviz_cfg.get("short_float", "over10"),
                min_avg_volume=finviz_cfg.get("average_volume", "over200k"),
                min_price=finviz_cfg.get("price", "over1"),
            )
            if not df.empty:
                ticker_col = "Ticker" if "Ticker" in df.columns else df.columns[1]
                tickers = df[ticker_col].tolist()
                logger.info("[red] Finviz returned %d candidates.", len(tickers))
                return tickers
        except Exception:
            logger.exception("[red] Finviz screening failed, falling back to curated list.")

        # Fallback: well-known high-short-interest tickers for testing
        return self._fallback_tickers()

    def _fallback_tickers(self) -> list[str]:
        """Curated list of historically high short interest tickers for testing.

        Periodically audit: remove delisted/bankrupt tickers (BBBY, RIDE, SKLZ,
        WISH were removed 2026-02).
        """
        return [
            "GME", "AMC", "CLOV", "SPCE", "WKHS",
            "GOEV", "RKT", "PLTR", "BB", "NOK", "FUBO",
            "MVIS", "SNDL", "TLRY", "SOFI", "MARA", "RIOT",
        ]

    # ------------------------------------------------------------------
    # Data collection for a single ticker
    # ------------------------------------------------------------------

    def _collect_short_data(self, ticker: str) -> Optional[ShortData]:
        """Gather all short-related metrics for a ticker.

        Includes validation: SI% > 100% is capped (likely data error,
        especially common with ADRs and foreign stocks).
        """
        info = market_data.get_ticker_info(ticker)
        if not info:
            return None

        short_pct = market_data.get_short_percent_of_float(ticker)
        if short_pct is None:
            # Try computing from raw values
            shares_short = info.get("sharesShort")
            float_shares = info.get("floatShares")
            if shares_short and float_shares and float_shares > 0:
                short_pct = (shares_short / float_shares) * 100
            else:
                return None

        # Sanity check: SI% > 100% is likely a data error (common with ADRs)
        if short_pct > 100:
            logger.warning(
                "[red] %s has implausible SI=%.1f%% (>100%%), capping at 100%%.",
                ticker, short_pct,
            )
            short_pct = 100.0

        return ShortData(
            ticker=ticker,
            short_float_pct=short_pct,
            short_shares=info.get("sharesShort"),
            days_to_cover=info.get("shortRatio"),
            borrow_fee_pct=None,  # Not freely available; Phase 2 via ORTEX
            float_shares=info.get("floatShares"),
            avg_volume=info.get("averageVolume"),
            put_call_ratio=self._compute_put_call_ratio(ticker),
            source="yfinance",
        )

    _MIN_PCR_VOLUME = 100  # Minimum total option volume for reliable P/C ratio

    def _compute_put_call_ratio(self, ticker: str) -> Optional[float]:
        """Compute put/call volume ratio from nearest expiration options.

        Returns None if total volume is below minimum threshold (low-volume
        P/C ratios are statistically unreliable).
        """
        expirations = market_data.get_options_expirations(ticker)
        if not expirations:
            return None

        calls, puts = market_data.get_options_chain(ticker, expirations[0])
        if calls.empty or puts.empty:
            return None

        call_vol = calls["volume"].sum() if "volume" in calls.columns else 0
        put_vol = puts["volume"].sum() if "volume" in puts.columns else 0

        # Require minimum total volume for a statistically meaningful ratio
        if call_vol + put_vol < self._MIN_PCR_VOLUME:
            return None
        if call_vol == 0:
            return None
        return float(put_vol / call_vol)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_short_intensity(self, data: ShortData) -> float:
        """Score 0-25: How heavily shorted is this stock?"""
        pct = data.short_float_pct
        if pct >= 40:
            return 25.0
        if pct >= 30:
            return 22.0
        if pct >= 20:
            return 18.0
        if pct >= 15:
            return 14.0
        if pct >= 10:
            return 10.0
        return max(0, pct * 0.8)

    def _score_cover_difficulty(self, data: ShortData) -> float:
        """Score 0-25: How hard is it for shorts to cover?"""
        score = 0.0

        # Days to cover: higher = harder to exit
        dtc = data.days_to_cover
        if dtc is not None:
            if dtc >= 10:
                score += 12.0
            elif dtc >= 7:
                score += 10.0
            elif dtc >= 5:
                score += 8.0
            elif dtc >= 3:
                score += 5.0
            else:
                score += dtc * 1.5

        # Float tightness: smaller float = more squeezable
        flt = data.float_shares
        if flt is not None:
            flt_millions = flt / 1e6
            if flt_millions < 10:
                score += 8.0
            elif flt_millions < 20:
                score += 6.0
            elif flt_millions < 50:
                score += 4.0
            elif flt_millions < 100:
                score += 2.0

        # Put/call ratio: high put/call = more bearish positioning (fuel)
        pcr = data.put_call_ratio
        if pcr is not None:
            if pcr > 2.0:
                score += 5.0
            elif pcr > 1.5:
                score += 3.0
            elif pcr > 1.0:
                score += 1.5

        return min(25.0, score)

    def _score_catalyst(self, ticker: str, hist: pd.DataFrame) -> float:
        """Score 0-25: Proximity to potential catalysts.

        Args:
            hist: Pre-fetched 3mo history (shared with _score_technical to
                  avoid duplicate API calls).
        """
        score = 0.0

        # Earnings proximity
        try:
            earnings = market_data.get_earnings_dates(ticker, limit=4)
            if not earnings.empty:
                now = datetime.now(timezone.utc)
                future_dates = earnings.index[earnings.index > now].sort_values()
                if len(future_dates) > 0:
                    days_until = (future_dates[0] - now).days
                    if days_until <= 7:
                        score += 12.0
                    elif days_until <= 14:
                        score += 8.0
                    elif days_until <= 30:
                        score += 4.0
        except Exception:
            pass

        # Relative volume (proxy for attention/activity)
        if not hist.empty and len(hist) > 5:
            rvol = technical.relative_volume(hist["Volume"], lookback=30)
            if rvol >= 5.0:
                score += 10.0
            elif rvol >= 3.0:
                score += 7.0
            elif rvol >= 2.0:
                score += 4.0
            elif rvol >= 1.5:
                score += 2.0

        return min(25.0, score)

    def _score_technical(self, hist: pd.DataFrame) -> float:
        """Score 0-25: Technical momentum and setup quality.

        Args:
            hist: Pre-fetched 3mo history (shared with _score_catalyst).
        """
        if hist.empty or len(hist) < 20:
            return 0.0

        score = 0.0
        close = hist["Close"]

        # RSI positioning (not overbought yet = room to run)
        rsi_vals = technical.rsi(close, period=14)
        if not rsi_vals.empty and not pd.isna(rsi_vals.iloc[-1]):
            current_rsi = rsi_vals.iloc[-1]
            if 50 <= current_rsi <= 70:
                score += 8.0  # Healthy momentum
            elif 40 <= current_rsi < 50:
                score += 5.0  # Building
            elif current_rsi < 40:
                score += 2.0  # Could bounce
            # Overbought (>70) gets 0: squeeze may already be playing out

        # Price above short-term MA (momentum confirmation)
        ma20 = technical.sma(close, 20)
        if not ma20.empty and not pd.isna(ma20.iloc[-1]):
            if close.iloc[-1] > ma20.iloc[-1]:
                score += 5.0

        # Recent 5-day return (positive momentum)
        if len(close) >= 6:
            ret_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100
            if 5 <= ret_5d <= 30:
                score += 7.0  # Strong but not exhausted
            elif 0 < ret_5d < 5:
                score += 3.0
            elif ret_5d > 30:
                score += 2.0  # May be overextended

        # MACD bullish crossover
        macd_line, signal_line, _ = technical.macd(close)
        if (not macd_line.empty and not signal_line.empty
                and not pd.isna(macd_line.iloc[-1]) and not pd.isna(signal_line.iloc[-1])):
            if macd_line.iloc[-1] > signal_line.iloc[-1]:
                score += 5.0

        return min(25.0, score)

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    def analyze(self, ticker: str) -> ScreenResult | None:
        """Full analysis pipeline for a single ticker."""
        data = self._collect_short_data(ticker)
        if data is None:
            logger.debug("[red] No short data for %s, skipping.", ticker)
            return None

        min_sf = self._team_cfg().get("min_short_float_pct", 10.0)
        if data.short_float_pct < min_sf:
            return None

        # Pre-fetch history once, share across scoring functions
        hist = market_data.get_history(ticker, period="3mo", interval="1d")

        s1 = self._score_short_intensity(data)
        s2 = self._score_cover_difficulty(data)
        s3 = self._score_catalyst(ticker, hist)
        s4 = self._score_technical(hist)
        total = s1 + s2 + s3 + s4

        return ScreenResult(
            ticker=ticker,
            team="red",
            score=total,
            signals={
                "short_intensity": s1,
                "cover_difficulty": s2,
                "catalyst_proximity": s3,
                "technical_momentum": s4,
                "short_float_pct": data.short_float_pct,
                "days_to_cover": data.days_to_cover or 0,
                "put_call_ratio": data.put_call_ratio or 0,
            },
            metadata={
                "float_shares": data.float_shares,
                "short_shares": data.short_shares,
                "avg_volume": data.avg_volume,
                "source": data.source,
            },
        )
