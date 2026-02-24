"""
Green Team: Low Float Breakout Special Ops

Phase 1 data sources:
  - Finviz free-tier (float screening, RVOL)
  - yfinance (OHLCV, float data, 52-week ranges)
  - pandas_ta / manual (RSI, MA, VWAP, OBV, ATR, Bollinger Bands)

Scoring model (0-100):
  - Float Tightness     (0-25): Float size, float utilization
  - Volume Explosion    (0-25): RVOL, volume trend, volume at key levels
  - Technical Setup     (0-25): RSI, MA alignment, Bollinger position, MACD
  - Breakout Quality    (0-25): Consolidation-breakout pattern, key levels, ATR expansion
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from src.core.base import BaseScreener
from src.core.data_types import ScreenResult, TechnicalSnapshot
from src.utils import finviz_scraper, market_data, technical

logger = logging.getLogger(__name__)


class LowFloatBreakoutScreener(BaseScreener):
    """Green Team screener: finds low-float stocks with breakout setups."""

    @property
    def team_name(self) -> str:
        return "green"

    def _team_cfg(self):
        return self.cfg["green_team"]

    # ------------------------------------------------------------------
    # Candidate discovery
    # ------------------------------------------------------------------

    def fetch_candidates(self) -> list[str]:
        """Fetch low-float, high-RVOL candidates from Finviz."""
        cfg = self._team_cfg()
        max_float = cfg.get("max_float_millions", 50)

        float_key = "under50m"
        if max_float <= 10:
            float_key = "under10m"
        elif max_float <= 20:
            float_key = "under20m"
        elif max_float <= 100:
            float_key = "under100m"

        try:
            df = finviz_scraper.get_low_float_candidates(
                max_float=float_key,
                min_rvol="over2",
                min_price="over1",
            )
            if not df.empty:
                ticker_col = "Ticker" if "Ticker" in df.columns else df.columns[1]
                tickers = df[ticker_col].tolist()
                logger.info("[green] Finviz returned %d low-float candidates.", len(tickers))
                return tickers
        except Exception:
            logger.exception("[green] Finviz low-float scan failed.")

        return self._fallback_tickers()

    def _fallback_tickers(self) -> list[str]:
        """Curated list of historically low-float momentum stocks."""
        return [
            "FFIE", "MULN", "ATER", "BBIG", "RDBX", "TBLT",
            "CLOV", "GOEV", "PROG", "ISPC", "ESSC", "BFRI",
            "IRNT", "SPRT", "NILE", "CEI", "FAMI", "PIXY",
        ]

    # ------------------------------------------------------------------
    # Technical snapshot
    # ------------------------------------------------------------------

    # Industries/sectors that produce false positives in breakout detection
    # (NAV-anchored pricing, trust structures, non-operating entities)
    _EXCLUDED_INDUSTRIES = frozenset({
        "Shell Companies",
        "Blank Checks",
        "Closed-End Fund - Equity",
        "Closed-End Fund - Debt",
        "Closed-End Fund - Foreign",
        "Exchange Traded Fund",
        "Special Purpose Acquisition",
    })

    def _build_snapshot_from_hist(self, ticker: str, hist: pd.DataFrame) -> Optional[TechnicalSnapshot]:
        """Build a comprehensive technical snapshot from pre-fetched history.

        Args:
            hist: 6mo daily OHLCV data (fetched once in analyze()).
        """
        info = market_data.get_ticker_info(ticker)

        # Filter out SPACs / shell companies -- their NAV-anchored prices
        # produce false positives in breakout detection.
        industry = info.get("industry", "")
        if industry in self._EXCLUDED_INDUSTRIES:
            logger.debug("[green] Skipping %s: excluded industry '%s'", ticker, industry)
            return None

        close = hist["Close"]
        high = hist["High"]
        low = hist["Low"]
        volume = hist["Volume"]

        latest_close = float(close.iloc[-1])
        latest_vol = int(volume.iloc[-1])

        # Price filter
        cfg = self._team_cfg()
        min_price = cfg.get("min_price", 1.0)
        max_price = cfg.get("max_price", 50.0)
        if latest_close < min_price or latest_close > max_price:
            return None

        # Compute indicators
        rsi_period = cfg.get("rsi_period", 14)
        rsi_vals = technical.rsi(close, period=rsi_period)

        ma_short = cfg.get("ma_short", 9)
        ma_medium = cfg.get("ma_medium", 20)
        ma_long = cfg.get("ma_long", 50)

        ma_9 = technical.sma(close, ma_short)
        ma_20 = technical.sma(close, ma_medium)
        ma_50 = technical.sma(close, ma_long)

        bb_period = cfg.get("bb_period", 20)
        bb_std = cfg.get("bb_std", 2.0)
        bb_upper, bb_mid, bb_lower = technical.bollinger_bands(close, bb_period, bb_std)

        atr_period = cfg.get("atr_period", 14)
        atr_vals = technical.atr(high, low, close, period=atr_period)

        obv_vals = technical.obv(close, volume)
        vwap_vals = technical.vwap(high, low, close, volume)

        rvol = technical.relative_volume(volume, lookback=30)

        # Float data
        float_shares = info.get("floatShares")

        # 52-week range
        high_52w = info.get("fiftyTwoWeekHigh")
        low_52w = info.get("fiftyTwoWeekLow")

        # Breakout detection
        is_breakout = technical.detect_breakout(
            hist,
            consolidation_days=cfg.get("consolidation_days", 10),
            volume_multiple=cfg.get("breakout_volume_multiple", 2.5),
            price_move_pct=cfg.get("breakout_price_pct", 3.0),
        )

        return TechnicalSnapshot(
            ticker=ticker,
            price=latest_close,
            volume=latest_vol,
            rvol=rvol,
            rsi=float(rsi_vals.iloc[-1]) if not rsi_vals.empty and not pd.isna(rsi_vals.iloc[-1]) else None,
            vwap=float(vwap_vals.iloc[-1]) if not vwap_vals.empty and not pd.isna(vwap_vals.iloc[-1]) else None,
            obv=float(obv_vals.iloc[-1]) if not obv_vals.empty and not pd.isna(obv_vals.iloc[-1]) else None,
            atr=float(atr_vals.iloc[-1]) if not atr_vals.empty and not pd.isna(atr_vals.iloc[-1]) else None,
            bb_upper=float(bb_upper.iloc[-1]) if not bb_upper.empty and not pd.isna(bb_upper.iloc[-1]) else None,
            bb_lower=float(bb_lower.iloc[-1]) if not bb_lower.empty and not pd.isna(bb_lower.iloc[-1]) else None,
            ma_9=float(ma_9.iloc[-1]) if not ma_9.empty and not pd.isna(ma_9.iloc[-1]) else None,
            ma_20=float(ma_20.iloc[-1]) if not ma_20.empty and not pd.isna(ma_20.iloc[-1]) else None,
            ma_50=float(ma_50.iloc[-1]) if not ma_50.empty and not pd.isna(ma_50.iloc[-1]) else None,
            float_shares=float_shares,
            high_52w=high_52w,
            low_52w=low_52w,
            is_breakout=is_breakout,
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_float_tightness(self, snap: TechnicalSnapshot) -> float:
        """Score 0-25: How tight is the float?"""
        score = 0.0
        flt = snap.float_shares

        if flt is None:
            return 2.0  # Unknown float: conservative default (no evidence of tightness)

        flt_millions = flt / 1e6

        # Smaller float = more explosive potential
        if flt_millions < 5:
            score += 15.0
        elif flt_millions < 10:
            score += 12.0
        elif flt_millions < 20:
            score += 9.0
        elif flt_millions < 50:
            score += 6.0
        elif flt_millions < 100:
            score += 3.0
        else:
            score += 1.0

        # Float utilization: RVOL relative to float (how much of float traded today?)
        if flt > 0 and snap.volume > 0:
            turnover = snap.volume / flt
            if turnover >= 1.0:
                score += 10.0  # Entire float traded in one day
            elif turnover >= 0.5:
                score += 7.0
            elif turnover >= 0.2:
                score += 4.0
            elif turnover >= 0.1:
                score += 2.0

        return min(25.0, score)

    def _score_volume_explosion(self, snap: TechnicalSnapshot) -> float:
        """Score 0-25: Volume surge magnitude."""
        score = 0.0

        rvol = snap.rvol
        if rvol >= 10.0:
            score += 15.0
        elif rvol >= 5.0:
            score += 12.0
        elif rvol >= 3.0:
            score += 9.0
        elif rvol >= 2.0:
            score += 6.0
        elif rvol >= 1.5:
            score += 3.0
        else:
            return 0.0  # Below RVOL threshold

        # Absolute volume check
        cfg = self._team_cfg()
        min_avg_vol = cfg.get("min_avg_volume", 100000)
        if snap.volume >= min_avg_vol * 5:
            score += 10.0
        elif snap.volume >= min_avg_vol * 2:
            score += 6.0
        elif snap.volume >= min_avg_vol:
            score += 3.0

        return min(25.0, score)

    def _score_technical_setup(self, snap: TechnicalSnapshot) -> float:
        """Score 0-25: Technical indicator alignment."""
        score = 0.0

        # RSI: ideal range for breakout setup
        if snap.rsi is not None:
            if 55 <= snap.rsi <= 75:
                score += 7.0  # Strong momentum, not yet exhausted
            elif 40 <= snap.rsi < 55:
                score += 4.0  # Building momentum
            elif snap.rsi < 35:
                score += 2.0  # Oversold bounce potential
            # >75 gets 0: already overextended

        # Moving average alignment (bullish stack: price > MA9 > MA20 > MA50)
        if all(v is not None for v in [snap.ma_9, snap.ma_20, snap.ma_50]):
            if snap.price > snap.ma_9 > snap.ma_20 > snap.ma_50:
                score += 7.0  # Perfect bullish alignment
            elif snap.price > snap.ma_9 > snap.ma_20:
                score += 5.0
            elif snap.price > snap.ma_20:
                score += 3.0

        # Bollinger Band position
        if snap.bb_upper is not None and snap.bb_lower is not None:
            bb_range = snap.bb_upper - snap.bb_lower
            if bb_range > 0:
                bb_position = (snap.price - snap.bb_lower) / bb_range
                if bb_position >= 0.9:
                    score += 6.0  # Breaking out of upper band
                elif bb_position >= 0.7:
                    score += 4.0
                elif bb_position <= 0.2:
                    score += 2.0  # Near lower band bounce

        # VWAP: price above VWAP is bullish
        if snap.vwap is not None and snap.price > snap.vwap:
            score += 5.0

        return min(25.0, score)

    def _score_breakout_quality(self, snap: TechnicalSnapshot, hist: pd.DataFrame) -> float:
        """Score 0-25: Breakout pattern quality and key level analysis.

        Args:
            hist: 6mo history from _build_snapshot (last ~21 rows used for OBV).
        """
        score = 0.0

        # Direct breakout detection
        if snap.is_breakout:
            score += 12.0

        # ATR expansion (volatility increase = breakout confirmation)
        if snap.atr is not None and snap.price > 0:
            atr_pct = snap.atr / snap.price * 100
            if atr_pct >= 8:
                score += 5.0  # High volatility expansion
            elif atr_pct >= 5:
                score += 3.0
            elif atr_pct >= 3:
                score += 1.0

        # 52-week high proximity (breaking new highs)
        if snap.high_52w is not None and snap.high_52w > 0:
            pct_from_high = (snap.high_52w - snap.price) / snap.high_52w * 100
            if pct_from_high <= 2:
                score += 8.0  # At or near 52-week high
            elif pct_from_high <= 5:
                score += 5.0
            elif pct_from_high <= 10:
                score += 3.0

        # OBV confirmation (rising OBV with rising price)
        # Use tail of the 6mo hist — OBV was already computed in _build_snapshot
        # but we reuse the last 21 days for trend comparison
        if not hist.empty and len(hist) >= 5:
            recent = hist.tail(21)
            obv_vals = technical.obv(recent["Close"], recent["Volume"])
            if not obv_vals.empty and len(obv_vals) >= 5:
                obv_trend = obv_vals.iloc[-1] - obv_vals.iloc[-5]
                price_trend = recent["Close"].iloc[-1] - recent["Close"].iloc[-5]
                if obv_trend > 0 and price_trend > 0:
                    score += 5.0  # Confirmed accumulation

        return min(25.0, score)

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    def analyze(self, ticker: str) -> ScreenResult | None:
        """Full analysis pipeline for a single ticker."""
        # Fetch 6mo history ONCE — used by _build_snapshot, _score_breakout_quality,
        # and support/resistance (eliminates 2 redundant get_history calls).
        hist = market_data.get_history(ticker, period="6mo", interval="1d")
        if hist.empty or len(hist) < 20:
            return None

        snap = self._build_snapshot_from_hist(ticker, hist)
        if snap is None:
            return None

        cfg = self._team_cfg()
        min_rvol = cfg.get("min_rvol", 2.0)
        if snap.rvol < min_rvol:
            return None

        s1 = self._score_float_tightness(snap)
        s2 = self._score_volume_explosion(snap)
        s3 = self._score_technical_setup(snap)
        s4 = self._score_breakout_quality(snap, hist)
        total = s1 + s2 + s3 + s4

        # Support/resistance from last 3mo slice (no extra API call)
        hist_3mo = hist.tail(63)  # ~3 months of trading days
        levels = technical.compute_support_resistance(hist_3mo) if not hist_3mo.empty else {"support": [], "resistance": []}

        return ScreenResult(
            ticker=ticker,
            team="green",
            score=total,
            signals={
                "float_tightness": s1,
                "volume_explosion": s2,
                "technical_setup": s3,
                "breakout_quality": s4,
                "rvol": snap.rvol,
                "rsi": snap.rsi or 0,
                "price": snap.price,
                "is_breakout": float(snap.is_breakout),
            },
            metadata={
                "float_shares": snap.float_shares,
                "volume": snap.volume,
                "ma_9": snap.ma_9,
                "ma_20": snap.ma_20,
                "ma_50": snap.ma_50,
                "bb_upper": snap.bb_upper,
                "bb_lower": snap.bb_lower,
                "vwap": snap.vwap,
                "atr": snap.atr,
                "high_52w": snap.high_52w,
                "low_52w": snap.low_52w,
                "support_levels": levels.get("support", []),
                "resistance_levels": levels.get("resistance", []),
            },
        )
