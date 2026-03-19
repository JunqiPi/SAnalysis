"""
Blue Team: Momentum + Catalyst Fusion Elite

Phase 1 data sources:
  - yfinance: historical prices, earnings dates, financials, analyst estimates
  - VIX via yfinance (^VIX)
  - Market breadth proxy via SPY

Scoring model (0-100):
  - Price Momentum       (0-25): Multi-timeframe returns, trend consistency
  - Catalyst Proximity   (0-25): Earnings date, earnings surprise history, analyst revisions
  - Financial Quality    (0-25): Revenue growth, margins, debt profile
  - Market Regime        (0-25): VIX level, SPY trend, sector relative strength
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from src.core.base import BaseScreener
from src.core.data_types import MomentumSnapshot, ScreenResult
from src.utils import finviz_scraper, market_data, technical

logger = logging.getLogger(__name__)


class MomentumCatalystScreener(BaseScreener):
    """Blue Team screener: identifies momentum setups with upcoming catalysts."""

    @property
    def team_name(self) -> str:
        return "blue"

    def _team_cfg(self):
        return self.cfg["blue_team"]

    # ------------------------------------------------------------------
    # Candidate discovery
    # ------------------------------------------------------------------

    def fetch_candidates(self) -> list[str]:
        """Fetch small-cap momentum candidates from Finviz.

        Phase 2 upgrade: replaced hardcoded large-cap list with dynamic
        Finviz screening for small caps (<$2B) with elevated RVOL.
        Large-cap stocks (AAPL, MSFT, etc.) are excluded by design --
        they cannot achieve the 10x returns this platform targets.
        """
        try:
            df = finviz_scraper.get_small_cap_momentum_candidates(
                max_cap="smallunder2b",
                min_rvol="over1.5",
                min_price="over1",
                min_avg_volume="over200k",
            )
            if not df.empty:
                ticker_col = "Ticker" if "Ticker" in df.columns else df.columns[1]
                tickers = df[ticker_col].tolist()
                logger.info("[blue] Finviz returned %d small-cap momentum candidates.", len(tickers))
                return tickers
            else:
                logger.warning("[blue] Finviz returned empty, falling back to curated list.")
        except Exception:
            logger.exception("[blue] Finviz small-cap scan failed, falling back to curated list.")

        return self._fallback_tickers()

    def _fallback_tickers(self) -> list[str]:
        """Curated list of small/micro-cap momentum stocks.

        All tickers must be under $10B market cap. Large caps
        (AAPL, MSFT, GOOG, NVDA, META, AMZN) are explicitly excluded
        as they cannot achieve 10x returns in a reasonable timeframe.
        """
        return [
            # Meme/squeeze-adjacent small caps
            "GME", "AMC", "PLTR", "SOFI", "CLOV", "FUBO",
            # EV small caps
            "GOEV", "RIVN", "LCID", "NIO",
            # Crypto-adjacent
            "MARA", "RIOT", "COIN", "HOOD",
            # High-beta small caps
            "UPST", "DKNG", "RBLX",
            # Biotech catalyst plays
            "CRSP",
        ]

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def _build_snapshot(self, ticker: str) -> Optional[MomentumSnapshot]:
        """Build a momentum + catalyst snapshot."""
        cfg = self._team_cfg()
        lookback = cfg.get("lookback_months", 6)
        period = f"{lookback}mo"

        hist = market_data.get_history(ticker, period=period, interval="1d")
        if hist.empty or len(hist) < 21:
            return None

        close = hist["Close"]
        snap = MomentumSnapshot(ticker=ticker)

        # Multi-timeframe momentum (returns over N trading days)
        momentum_periods = cfg.get("momentum_periods", [5, 10, 21, 63, 126, 252])
        returns = {}
        for p in momentum_periods:
            if len(close) > p:
                ret = (close.iloc[-1] / close.iloc[-(p + 1)] - 1) * 100
                returns[f"mom_{p}d"] = float(ret)

        snap.momentum_5d = returns.get("mom_5d")
        snap.momentum_21d = returns.get("mom_21d")
        snap.momentum_63d = returns.get("mom_63d")

        # Composite momentum score
        snap.momentum_score = self._compute_momentum_score(returns)

        # Earnings data
        self._attach_earnings_data(snap, ticker)

        # Financial quality
        self._attach_financial_data(snap, ticker)

        # Market regime
        self._attach_market_regime(snap)

        return snap

    def _compute_momentum_score(self, returns: dict[str, float]) -> float:
        """Compute a 0-100 composite momentum score from multi-timeframe returns.

        Weights:
          - 5d:  15% (very recent momentum)
          - 21d: 25% (one-month trend)
          - 63d: 30% (quarterly trend, most important)
          - 126d: 20% (half-year trend)
          - 252d: 10% (yearly trend)
        """
        weights = {
            "mom_5d": 0.15,
            "mom_10d": 0.0,   # Included in data but not weighted independently
            "mom_21d": 0.25,
            "mom_63d": 0.30,
            "mom_126d": 0.20,
            "mom_252d": 0.10,
        }

        total_weight = 0.0
        weighted_sum = 0.0

        for key, weight in weights.items():
            if key in returns and weight > 0:
                ret = returns[key]
                # Normalize: symmetric range [-50, +50] → [0, 100]
                # 0% return = 50 (neutral), -50% = 0, +50% = 100
                normalized = max(0.0, min(100.0, ret + 50.0))
                weighted_sum += normalized * weight
                total_weight += weight

        if total_weight == 0:
            return 0.0

        return weighted_sum / total_weight

    def _attach_earnings_data(self, snap: MomentumSnapshot, ticker: str) -> None:
        """Attach earnings date and surprise data to snapshot."""
        try:
            earnings = market_data.get_earnings_dates(ticker, limit=8)
            if earnings.empty:
                return

            now = datetime.now(timezone.utc)

            # Find next upcoming earnings (sort ascending to get closest date)
            future = earnings.index[earnings.index > now].sort_values()
            if len(future) > 0:
                next_date = future[0]
                snap.earnings_date = next_date.strftime("%Y-%m-%d")
                snap.days_to_earnings = (next_date - now).days

            # EPS estimate from earnings data
            if "EPS Estimate" in earnings.columns:
                est = earnings["EPS Estimate"].dropna()
                if not est.empty:
                    snap.eps_estimate = float(est.iloc[0])

        except Exception:
            logger.debug("[blue] Earnings data unavailable for %s", ticker, exc_info=True)

    def _attach_financial_data(self, snap: MomentumSnapshot, ticker: str) -> None:
        """Attach key financial metrics to snapshot."""
        info = market_data.get_ticker_info(ticker)

        # Revenue growth (YoY)
        snap.revenue_growth_pct = info.get("revenueGrowth")
        if snap.revenue_growth_pct is not None:
            snap.revenue_growth_pct = snap.revenue_growth_pct * 100  # Convert to percentage

        # Debt to equity
        snap.debt_to_equity = info.get("debtToEquity")
        if snap.debt_to_equity is not None:
            snap.debt_to_equity = snap.debt_to_equity / 100  # yfinance reports as percentage

    def _attach_market_regime(self, snap: MomentumSnapshot) -> None:
        """Determine current market regime from VIX and SPY."""
        cfg = self._team_cfg()

        vix = market_data.get_vix()
        snap.vix_level = vix

        vix_high = cfg.get("vix_high_threshold", 25)
        vix_low = cfg.get("vix_low_threshold", 15)

        if vix is not None:
            if vix >= vix_high:
                snap.market_regime = "risk_off"
            elif vix <= vix_low:
                snap.market_regime = "risk_on"
            else:
                snap.market_regime = "neutral"

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_momentum(self, snap: MomentumSnapshot) -> float:
        """Score 0-25: Price momentum strength and consistency."""
        score = 0.0

        # Composite momentum score (0-100) -> scale to 0-15
        score += snap.momentum_score * 0.15

        # Trend consistency: are all timeframes positive?
        timeframes = [snap.momentum_5d, snap.momentum_21d, snap.momentum_63d]
        valid_tf = [t for t in timeframes if t is not None]
        if valid_tf:
            positive_count = sum(1 for t in valid_tf if t > 0)
            consistency = positive_count / len(valid_tf)
            score += consistency * 10.0

        return min(25.0, score)

    def _score_catalyst(self, snap: MomentumSnapshot) -> float:
        """Score 0-25: Catalyst proximity and quality."""
        score = 0.0
        cfg = self._team_cfg()
        lookahead = cfg.get("earnings_lookahead_days", 14)

        # Earnings proximity
        if snap.days_to_earnings is not None:
            days = snap.days_to_earnings
            if 0 < days <= 7:
                score += 15.0  # Imminent earnings
            elif days <= 14:
                score += 10.0
            elif days <= 30:
                score += 5.0
            elif days <= 60:
                score += 2.0

        # EPS estimate presence (tracked by analysts = more attention)
        if snap.eps_estimate is not None:
            score += 5.0

        # Note: revenue_growth is scored in _score_financial_quality only,
        # to avoid double-counting the same metric across two factors.

        return min(25.0, score)

    def _score_financial_quality(self, snap: MomentumSnapshot) -> float:
        """Score 0-25: Financial health and growth profile.

        Meme-stock friendly: every stock starts with a 5pt baseline.
        Poor financials reduce from 25 but never below the baseline,
        because momentum strategies should not disqualify stocks solely
        on fundamental weakness.
        """
        # Baseline: momentum candidates deserve a floor — financial quality
        # is a modifier, not a disqualifier in a meme-stock context.
        score = 5.0
        cfg = self._team_cfg()

        # Revenue growth (0-8 additional)
        if snap.revenue_growth_pct is not None:
            growth = snap.revenue_growth_pct
            min_growth = cfg.get("min_revenue_growth_pct", 10.0)
            if growth >= 100:
                score += 8.0
            elif growth >= 50:
                score += 6.0
            elif growth >= min_growth:
                score += 4.0
            elif growth >= 0:
                score += 2.0
            elif growth >= -20:
                score += 1.0  # Slight decline, not catastrophic

        # Debt profile (0-5 additional)
        # Negative D/E means negative shareholder equity (insolvency),
        # NOT low debt. Score 0 additional points for insolvent companies.
        max_de = cfg.get("max_debt_to_equity", 3.0)
        if snap.debt_to_equity is not None:
            de = snap.debt_to_equity
            if de < 0:
                pass  # Insolvent: negative equity, 0 additional points
            elif de < 0.5:
                score += 5.0  # Very low debt
            elif de < 1.0:
                score += 4.0
            elif de < max_de:
                score += 2.0

        # Analyst coverage (0-5 additional, reduced from 7 -- many 10x candidates lack coverage)
        if snap.eps_estimate is not None:
            score += 5.0
        else:
            # Under-the-radar bonus: unanalyzed stocks have more 10x potential
            score += 2.0

        return min(25.0, score)

    def _score_market_regime(self, snap: MomentumSnapshot) -> float:
        """Score 0-25: Market environment favorability for momentum."""
        score = 0.0

        # VIX-based regime
        if snap.market_regime == "risk_on":
            score += 15.0
        elif snap.market_regime == "neutral":
            score += 10.0
        elif snap.market_regime == "risk_off":
            score += 3.0  # Momentum less reliable in high-vol regimes

        # VIX level detail
        if snap.vix_level is not None:
            if snap.vix_level < 12:
                score += 5.0  # Very calm: complacency can lead to moves
            elif snap.vix_level < 15:
                score += 4.0
            elif snap.vix_level < 20:
                score += 3.0
            elif snap.vix_level < 25:
                score += 2.0
            else:
                score += 1.0

        # Market breadth (SPY trend as proxy)
        breadth = market_data.get_market_breadth()
        if breadth:
            spy_5d = breadth.get("spy_5d_return", 0)
            if spy_5d > 2:
                score += 5.0
            elif spy_5d > 0:
                score += 3.0
            elif spy_5d > -2:
                score += 1.0

        return min(25.0, score)

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    def analyze(self, ticker: str) -> ScreenResult | None:
        """Full analysis pipeline for a single ticker.

        Applies:
        - Momentum gate (min_momentum_score from config)
        - VIX regime multiplier: discounts total score when VIX is elevated,
          so momentum signals are proportionally downweighted in high-vol regimes.
        """
        snap = self._build_snapshot(ticker)
        if snap is None:
            return None

        # Market cap gate: exclude stocks too large for 10x potential
        cfg = self._team_cfg()
        info = market_data.get_ticker_info(ticker)
        mcap = info.get("marketCap") if info else None
        max_mcap = cfg.get("max_market_cap_millions", 2000)
        if mcap is not None and mcap > max_mcap * 1e6:
            logger.debug(
                "[blue] %s market cap $%.1fB exceeds max $%.1fB, skipping.",
                ticker, mcap / 1e9, max_mcap / 1e3,
            )
            return None

        # Momentum gate: skip tickers below minimum momentum threshold
        min_mom = cfg.get("min_momentum_score", 0)
        if min_mom > 0 and snap.momentum_score < min_mom:
            logger.debug(
                "[blue] %s momentum_score=%.1f below threshold %d, skipping.",
                ticker, snap.momentum_score, min_mom,
            )
            return None

        s1 = self._score_momentum(snap)
        s2 = self._score_catalyst(snap)
        s3 = self._score_financial_quality(snap)
        s4 = self._score_market_regime(snap)
        raw_total = s1 + s2 + s3 + s4

        # VIX regime multiplier: momentum strategies are unreliable in high-vol.
        # This is the "safety valve" — it affects the total score, not just the
        # market_regime factor, ensuring elevated VIX truly suppresses rankings.
        vix_high = cfg.get("vix_high_threshold", 25)
        regime_multiplier = 1.0
        if snap.vix_level is not None:
            if snap.vix_level >= 35:
                regime_multiplier = 0.5   # Red alert: massive discount
            elif snap.vix_level >= vix_high:
                regime_multiplier = 0.7   # Yellow warning: significant discount

        total = raw_total * regime_multiplier

        return ScreenResult(
            ticker=ticker,
            team="blue",
            score=total,
            signals={
                "price_momentum": s1,
                "catalyst_proximity": s2,
                "financial_quality": s3,
                "market_regime": s4,
                "momentum_score": snap.momentum_score,
                "momentum_5d": snap.momentum_5d or 0,
                "momentum_21d": snap.momentum_21d or 0,
                "momentum_63d": snap.momentum_63d or 0,
                "vix_level": snap.vix_level or 0,
            },
            metadata={
                "earnings_date": snap.earnings_date,
                "days_to_earnings": snap.days_to_earnings,
                "eps_estimate": snap.eps_estimate,
                "revenue_growth_pct": snap.revenue_growth_pct,
                "debt_to_equity": snap.debt_to_equity,
                "market_regime": snap.market_regime,
                "regime_multiplier": regime_multiplier,
                "market_cap_millions": mcap / 1e6 if mcap else None,
            },
        )
