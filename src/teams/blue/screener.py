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
from src.utils import market_data, technical

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
        """Return tickers to analyze for momentum + catalyst setups.

        Phase 1: curated list of stocks known for momentum plays.
        Phase 2+: will use screener APIs for momentum scans.
        """
        return [
            # High-beta momentum names
            "TSLA", "NVDA", "AMD", "META", "AMZN", "AAPL", "MSFT", "GOOG",
            # Meme/squeeze adjacent
            "GME", "AMC", "PLTR", "SOFI", "RIVN", "LCID", "NIO",
            # Biotech/catalyst-driven
            "MRNA", "BNTX", "CRSP",
            # Recent IPO/SPAC momentum
            "HOOD", "COIN", "RBLX", "DKNG", "UPST",
            # Small-cap momentum
            "FUBO", "CLOV", "MARA", "RIOT",
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
                # Normalize: clip returns to [-50, 100] range, then scale to 0-100
                normalized = max(0, min(100, (ret + 50) * (100 / 150)))
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

            # Find next upcoming earnings
            future = earnings.index[earnings.index > now]
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
            logger.debug("[blue] Earnings data unavailable for %s", ticker)

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

        # Revenue growth as catalyst signal
        if snap.revenue_growth_pct is not None:
            growth = snap.revenue_growth_pct
            if growth >= 50:
                score += 5.0
            elif growth >= 20:
                score += 3.0
            elif growth >= 10:
                score += 1.0

        return min(25.0, score)

    def _score_financial_quality(self, snap: MomentumSnapshot) -> float:
        """Score 0-25: Financial health and growth profile."""
        score = 0.0
        cfg = self._team_cfg()

        # Revenue growth
        if snap.revenue_growth_pct is not None:
            growth = snap.revenue_growth_pct
            min_growth = cfg.get("min_revenue_growth_pct", 10.0)
            if growth >= 100:
                score += 10.0
            elif growth >= 50:
                score += 8.0
            elif growth >= min_growth:
                score += 5.0
            elif growth >= 0:
                score += 2.0
            # Negative growth gets 0

        # Debt profile
        max_de = cfg.get("max_debt_to_equity", 3.0)
        if snap.debt_to_equity is not None:
            de = snap.debt_to_equity
            if de < 0.5:
                score += 8.0  # Very low debt
            elif de < 1.0:
                score += 6.0
            elif de < max_de:
                score += 3.0
            else:
                score += 0.0  # Over-leveraged

        # If no financial data available, give moderate default
        if snap.revenue_growth_pct is None and snap.debt_to_equity is None:
            score = 8.0

        # Analyst coverage (EPS estimate = covered by analysts)
        if snap.eps_estimate is not None:
            score += 7.0

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
        """Full analysis pipeline for a single ticker."""
        snap = self._build_snapshot(ticker)
        if snap is None:
            return None

        s1 = self._score_momentum(snap)
        s2 = self._score_catalyst(snap)
        s3 = self._score_financial_quality(snap)
        s4 = self._score_market_regime(snap)
        total = s1 + s2 + s3 + s4

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
            },
        )
