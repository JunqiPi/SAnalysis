"""
Technical indicator calculations built on pandas_ta.

Provides a clean wrapper so team modules don't directly depend
on pandas_ta's API -- making it trivial to swap backends later.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Attempt pandas_ta import; fall back to manual implementations if missing
try:
    import pandas_ta as ta
    _HAS_PANDAS_TA = True
except ImportError:
    _HAS_PANDAS_TA = False
    logger.warning("pandas_ta not installed; using manual indicator implementations.")


# ------------------------------------------------------------------
# Core indicators
# ------------------------------------------------------------------

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    if _HAS_PANDAS_TA:
        result = ta.rsi(series, length=period)
        return result if result is not None else pd.Series(dtype=float)

    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    if _HAS_PANDAS_TA:
        result = ta.sma(series, length=period)
        return result if result is not None else pd.Series(dtype=float)
    return series.rolling(window=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    if _HAS_PANDAS_TA:
        result = ta.ema(series, length=period)
        return result if result is not None else pd.Series(dtype=float)
    return series.ewm(span=period, adjust=False).mean()


def bollinger_bands(
    series: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands: returns (upper, middle, lower)."""
    if _HAS_PANDAS_TA:
        bb = ta.bbands(series, length=period, std=std_dev)
        if bb is not None and not bb.empty:
            cols = bb.columns.tolist()
            # pandas_ta returns BBL, BBM, BBU, BBB, BBP
            lower = bb[cols[0]]
            mid = bb[cols[1]]
            upper = bb[cols[2]]
            return upper, mid, lower

    mid = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range."""
    if _HAS_PANDAS_TA:
        result = ta.atr(high, low, close, length=period)
        return result if result is not None else pd.Series(dtype=float)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    if _HAS_PANDAS_TA:
        result = ta.obv(close, volume)
        return result if result is not None else pd.Series(dtype=float)

    direction = np.sign(close.diff()).fillna(0)
    return (volume * direction).cumsum()


def vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """Volume-Weighted Average Price (cumulative intraday-style).

    For daily data this computes a running VWAP over the available window.
    """
    if _HAS_PANDAS_TA:
        result = ta.vwap(high, low, close, volume)
        if result is not None:
            return result

    typical_price = (high + low + close) / 3
    cum_tp_vol = (typical_price * volume).cumsum()
    cum_vol = volume.cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD: returns (macd_line, signal_line, histogram)."""
    if _HAS_PANDAS_TA:
        result = ta.macd(series, fast=fast, slow=slow, signal=signal)
        if result is not None and not result.empty:
            cols = result.columns.tolist()
            return result[cols[0]], result[cols[1]], result[cols[2]]

    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ------------------------------------------------------------------
# Derived / composite
# ------------------------------------------------------------------

def relative_volume(volume: pd.Series, lookback: int = 30) -> float:
    """Current volume relative to N-day average volume.

    Returns the ratio of the latest bar's volume to the average.
    If fewer than *lookback* bars are available, uses all prior bars.
    """
    if len(volume) < 2:
        return 1.0
    # Use min(lookback, available) to avoid empty slice when data is short
    available = len(volume) - 1
    window = min(lookback, available)
    avg = volume.iloc[-window - 1:-1].mean()
    if avg == 0 or pd.isna(avg):
        return 1.0
    return float(volume.iloc[-1] / avg)


def detect_breakout(
    df: pd.DataFrame,
    consolidation_days: int = 10,
    volume_multiple: float = 2.5,
    price_move_pct: float = 3.0,
) -> bool:
    """Detect if the latest bar is an *upside* volume-breakout from consolidation.

    Criteria:
      1. Price range during consolidation_days was tight (< 3x ATR).
      2. Latest bar's volume > volume_multiple * average volume.
      3. Latest bar closed *higher* than previous close by >= price_move_pct %.

    Note: Only upside breakouts are detected.  Downside crashes (earnings
    collapses, etc.) are explicitly excluded -- they are not breakout setups.
    """
    if len(df) < consolidation_days + 2:
        return False

    window = df.iloc[-(consolidation_days + 1):-1]
    latest = df.iloc[-1]

    # Price range during consolidation
    price_range = window["High"].max() - window["Low"].min()
    avg_atr_val = atr(df["High"], df["Low"], df["Close"], period=14).iloc[-2]
    if pd.isna(avg_atr_val) or avg_atr_val == 0:
        return False

    # Consolidation check: range should be relatively tight
    if price_range > 3 * avg_atr_val:
        return False

    # Volume surge
    avg_vol = window["Volume"].mean()
    if avg_vol == 0:
        return False
    vol_ratio = latest["Volume"] / avg_vol
    if vol_ratio < volume_multiple:
        return False

    # Price move -- MUST be upside (close > prev_close)
    prev_close = df["Close"].iloc[-2]
    if prev_close == 0:
        return False
    price_change = latest["Close"] - prev_close
    if price_change <= 0:
        return False  # Downside move is NOT a breakout
    pct_move = price_change / prev_close * 100
    return pct_move >= price_move_pct


def compute_support_resistance(
    df: pd.DataFrame,
    window: int = 20,
    num_levels: int = 3,
) -> dict[str, list[float]]:
    """Identify key support and resistance levels using local extrema.

    Uses numpy vectorized rolling min/max comparison instead of
    inner Python loops, reducing O(n*window) to O(n) via rolling ops.

    Returns dict with 'support' and 'resistance' lists (sorted).
    """
    if len(df) < window:
        return {"support": [], "resistance": []}

    highs = df["High"]
    lows = df["Low"]

    # Vectorized approach: rolling min/max over the window
    roll_low_min = lows.rolling(window=window, center=True).min()
    roll_high_max = highs.rolling(window=window, center=True).max()

    # Support: points where the low equals the rolling minimum
    support_mask = (lows == roll_low_min) & roll_low_min.notna()
    supports = lows[support_mask].tolist()

    # Resistance: points where the high equals the rolling maximum
    resistance_mask = (highs == roll_high_max) & roll_high_max.notna()
    resistances = highs[resistance_mask].tolist()

    # Deduplicate close levels (within 1% of each other)
    supports = _cluster_levels(sorted(supports), pct=0.01)
    resistances = _cluster_levels(sorted(resistances, reverse=True), pct=0.01)

    return {
        "support": supports[:num_levels],
        "resistance": resistances[:num_levels],
    }


def _cluster_levels(levels: list[float], pct: float) -> list[float]:
    """Merge price levels that are within *pct* of each other."""
    if not levels:
        return []
    clustered = [levels[0]]
    for lvl in levels[1:]:
        if abs(lvl - clustered[-1]) / max(clustered[-1], 1e-9) > pct:
            clustered.append(lvl)
    return clustered
