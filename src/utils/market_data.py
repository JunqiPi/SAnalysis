"""
Centralized market data fetching via yfinance.

All teams route through this module so we get:
  - Unified caching (no duplicate API calls for the same ticker)
  - Consistent error handling
  - Single point to swap data providers in future phases
  - Ticker object reuse to minimize redundant Yahoo Finance sessions

NOTE on network timeouts:
  yfinance manages its own internal ``requests.Session`` and does not
  expose a ``timeout`` parameter on public methods (`.history()`,
  `.info`, `.option_chain()`, etc.).  The ``general.network_timeout_seconds``
  config key is therefore enforced only in modules that make direct
  ``requests`` calls (e.g., ``finviz_scraper``).  If yfinance hangs,
  the ThreadPoolExecutor in the orchestrator will still bound wall-clock
  time per team via OS-level socket timeouts (typically 60-120 s).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

import pandas as pd
import yfinance as yf

from src.core.cache import (
    cache_dataframe,
    cache_json,
    load_cached_dataframe,
    load_cached_json,
)

logger = logging.getLogger(__name__)

# Reuse yf.Ticker objects to avoid redundant session initialization.
# Thread-safe via a lock because the orchestrator uses ThreadPoolExecutor.
_ticker_cache: dict[str, yf.Ticker] = {}
_ticker_lock = threading.Lock()


def _get_yf_ticker(symbol: str) -> yf.Ticker:
    """Return a (possibly cached) yfinance Ticker object."""
    if symbol not in _ticker_cache:
        with _ticker_lock:
            if symbol not in _ticker_cache:
                _ticker_cache[symbol] = yf.Ticker(symbol)
    return _ticker_cache[symbol]


# ------------------------------------------------------------------
# Price / OHLCV
# ------------------------------------------------------------------

def get_history(
    ticker: str,
    period: str = "6mo",
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch OHLCV history for a ticker with caching.

    Args:
        ticker: Stock symbol (e.g. "GME").
        period: yfinance period string ("1mo", "3mo", "6mo", "1y", "2y", "max").
        interval: Bar interval ("1m", "5m", "15m", "1h", "1d", "1wk").

    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume, plus Adj Close if available.
    """
    cache_key = f"{ticker}_{period}_{interval}"
    cached = load_cached_dataframe("history", cache_key)
    if cached is not None:
        return cached

    try:
        tk = _get_yf_ticker(ticker)
        df = tk.history(period=period, interval=interval, auto_adjust=False)
        if df.empty:
            logger.warning("No history data for %s (period=%s, interval=%s)", ticker, period, interval)
            return pd.DataFrame()
        cache_dataframe("history", cache_key, df)
        return df
    except Exception:
        logger.exception("Failed to fetch history for %s", ticker)
        return pd.DataFrame()


def get_current_price(ticker: str) -> Optional[float]:
    """Get the most recent closing price for a ticker."""
    df = get_history(ticker, period="5d", interval="1d")
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])


# ------------------------------------------------------------------
# Fundamental / Info
# ------------------------------------------------------------------

def get_ticker_info(ticker: str) -> dict[str, Any]:
    """Fetch the full info dict from yfinance (cached).

    Includes: marketCap, floatShares, sharesShort, shortRatio,
    shortPercentOfFloat, averageVolume, fiftyTwoWeekHigh/Low, etc.
    """
    cached = load_cached_json("info", ticker)
    if cached is not None:
        return cached

    try:
        tk = _get_yf_ticker(ticker)
        info = tk.info or {}
        # yfinance .info may contain non-serializable objects; sanitize
        clean = {k: v for k, v in info.items() if isinstance(v, (str, int, float, bool, type(None), list))}
        cache_json("info", ticker, clean)
        return clean
    except Exception:
        logger.exception("Failed to fetch info for %s", ticker)
        return {}


def get_float_shares(ticker: str) -> Optional[int]:
    info = get_ticker_info(ticker)
    return info.get("floatShares")


def get_shares_short(ticker: str) -> Optional[int]:
    info = get_ticker_info(ticker)
    return info.get("sharesShort")


def get_short_ratio(ticker: str) -> Optional[float]:
    """Days-to-cover (short ratio) from yfinance."""
    info = get_ticker_info(ticker)
    return info.get("shortRatio")


def get_short_percent_of_float(ticker: str) -> Optional[float]:
    """Short interest as percentage of float."""
    info = get_ticker_info(ticker)
    val = info.get("shortPercentOfFloat")
    if val is not None:
        return val * 100  # yfinance returns as decimal (0.15 = 15%)
    return None


# ------------------------------------------------------------------
# Options chain
# ------------------------------------------------------------------

def get_options_expirations(ticker: str) -> list[str]:
    """Return available option expiration dates."""
    try:
        tk = _get_yf_ticker(ticker)
        return list(tk.options)
    except Exception:
        logger.exception("Failed to get options expirations for %s", ticker)
        return []


def get_options_chain(ticker: str, expiration: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch calls and puts for a specific expiration.

    Returns:
        (calls_df, puts_df) -- each with columns:
        strike, lastPrice, bid, ask, volume, openInterest, impliedVolatility, etc.
    """
    cache_key = f"{ticker}_{expiration}"
    cached_calls = load_cached_dataframe("opt_calls", cache_key)
    cached_puts = load_cached_dataframe("opt_puts", cache_key)
    if cached_calls is not None and cached_puts is not None:
        return cached_calls, cached_puts

    try:
        tk = _get_yf_ticker(ticker)
        chain = tk.option_chain(expiration)
        calls = chain.calls
        puts = chain.puts
        cache_dataframe("opt_calls", cache_key, calls)
        cache_dataframe("opt_puts", cache_key, puts)
        return calls, puts
    except Exception:
        logger.exception("Failed to fetch option chain for %s exp=%s", ticker, expiration)
        return pd.DataFrame(), pd.DataFrame()


# ------------------------------------------------------------------
# Earnings / Calendar
# ------------------------------------------------------------------

def get_earnings_dates(ticker: str, limit: int = 4) -> pd.DataFrame:
    """Fetch upcoming and recent earnings dates."""
    try:
        tk = _get_yf_ticker(ticker)
        dates = tk.get_earnings_dates(limit=limit)
        if dates is not None and not dates.empty:
            return dates
    except Exception:
        logger.exception("Failed to get earnings dates for %s", ticker)
    return pd.DataFrame()


def get_financials(ticker: str) -> dict[str, pd.DataFrame]:
    """Fetch income statement, balance sheet, and cash flow."""
    try:
        tk = _get_yf_ticker(ticker)
        return {
            "income": tk.financials if tk.financials is not None else pd.DataFrame(),
            "balance": tk.balance_sheet if tk.balance_sheet is not None else pd.DataFrame(),
            "cashflow": tk.cashflow if tk.cashflow is not None else pd.DataFrame(),
        }
    except Exception:
        logger.exception("Failed to get financials for %s", ticker)
        return {"income": pd.DataFrame(), "balance": pd.DataFrame(), "cashflow": pd.DataFrame()}


# ------------------------------------------------------------------
# Market-wide / VIX
# ------------------------------------------------------------------

def get_vix() -> Optional[float]:
    """Get current VIX level."""
    df = get_history("^VIX", period="5d", interval="1d")
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])


def get_market_breadth() -> dict[str, Any]:
    """Basic market breadth: SPY recent performance as a proxy.

    In Phase 2+, this will be replaced with proper advance/decline data.
    """
    spy = get_history("SPY", period="1mo", interval="1d")
    if spy.empty:
        return {}

    close = spy["Close"]
    return {
        "spy_1d_return": float((close.iloc[-1] / close.iloc[-2] - 1) * 100) if len(close) >= 2 else 0,
        "spy_5d_return": float((close.iloc[-1] / close.iloc[-5] - 1) * 100) if len(close) >= 5 else 0,
        "spy_21d_return": float((close.iloc[-1] / close.iloc[-21] - 1) * 100) if len(close) >= 21 else 0,
        "spy_last_close": float(close.iloc[-1]),
    }
