"""
Canonical data structures shared across all teams.

Every team module produces one or more of these typed DataFrames /
dataclasses so downstream consumers never guess at column names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd


def _utcnow() -> datetime:
    """Timezone-aware UTC timestamp (replaces deprecated datetime.utcnow)."""
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------
# Ticker-level screening result
# ------------------------------------------------------------------

@dataclass
class ScreenResult:
    """A single ticker's screening outcome from any team."""
    ticker: str
    team: str                     # "red" | "orange" | "yellow" | "green" | "blue"
    score: float                  # 0-100 composite score
    signals: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        """Serialize to a flat dict for DataFrame construction.

        Includes both signal columns (prefixed 'sig_') and metadata
        columns (prefixed 'meta_') for full data preservation.
        """
        d = {
            "ticker": self.ticker,
            "team": self.team,
            "score": self.score,
            **{f"sig_{k}": v for k, v in self.signals.items()},
            "timestamp": self.timestamp.isoformat(),
        }
        # Include scalar metadata (skip complex types like lists/dicts
        # that can't be cleanly represented in a flat DataFrame row)
        for k, v in self.metadata.items():
            if isinstance(v, (int, float, str, bool, type(None))):
                d[f"meta_{k}"] = v
        return d


# ------------------------------------------------------------------
# Short squeeze data (Red Team)
# ------------------------------------------------------------------

@dataclass
class ShortData:
    ticker: str
    short_float_pct: float           # Short interest as % of float
    short_shares: Optional[int] = None
    days_to_cover: Optional[float] = None
    borrow_fee_pct: Optional[float] = None
    float_shares: Optional[int] = None
    avg_volume: Optional[int] = None
    put_call_ratio: Optional[float] = None
    source: str = ""
    as_of: Optional[datetime] = None  # When the short data was last reported


# ------------------------------------------------------------------
# Options chain snapshot (Orange Team)
# ------------------------------------------------------------------

@dataclass
class OptionsSnapshot:
    ticker: str
    expiration: str                  # "YYYY-MM-DD"
    calls: pd.DataFrame = field(default_factory=pd.DataFrame)
    puts: pd.DataFrame = field(default_factory=pd.DataFrame)
    total_call_volume: int = 0
    total_put_volume: int = 0
    total_call_oi: int = 0
    total_put_oi: int = 0
    put_call_ratio: float = 0.0      # Volume-based P/C ratio
    put_call_ratio_oi: float = 0.0   # OI-weighted P/C ratio (more stable)
    timestamp: datetime = field(default_factory=_utcnow)


# ------------------------------------------------------------------
# Sentiment snapshot (Yellow Team)
# ------------------------------------------------------------------

@dataclass
class SentimentSnapshot:
    ticker: str
    mention_count: int = 0
    avg_sentiment: float = 0.0       # -1.0 to 1.0
    bullish_pct: float = 0.0
    bearish_pct: float = 0.0
    neutral_pct: float = 0.0
    sources: list[str] = field(default_factory=list)
    trending_rank: Optional[int] = None
    google_trends_score: Optional[float] = None
    timestamp: datetime = field(default_factory=_utcnow)


# ------------------------------------------------------------------
# Technical snapshot (Green Team)
# ------------------------------------------------------------------

@dataclass
class TechnicalSnapshot:
    ticker: str
    price: float
    volume: int
    rvol: float                      # Relative volume
    rsi: Optional[float] = None
    vwap: Optional[float] = None
    obv: Optional[float] = None
    atr: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    ma_9: Optional[float] = None
    ma_20: Optional[float] = None
    ma_50: Optional[float] = None
    float_shares: Optional[int] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    is_breakout: bool = False
    timestamp: datetime = field(default_factory=_utcnow)


# ------------------------------------------------------------------
# Momentum + Catalyst snapshot (Blue Team)
# ------------------------------------------------------------------

@dataclass
class MomentumSnapshot:
    ticker: str
    momentum_score: float = 0.0      # 0-100
    momentum_5d: Optional[float] = None
    momentum_21d: Optional[float] = None
    momentum_63d: Optional[float] = None
    earnings_date: Optional[str] = None
    days_to_earnings: Optional[int] = None
    eps_estimate: Optional[float] = None
    revenue_growth_pct: Optional[float] = None
    debt_to_equity: Optional[float] = None
    vix_level: Optional[float] = None
    market_regime: str = "neutral"   # "risk_on" | "neutral" | "risk_off"
    timestamp: datetime = field(default_factory=_utcnow)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def results_to_dataframe(results: list[ScreenResult]) -> pd.DataFrame:
    """Convert a list of ScreenResult into a sorted DataFrame."""
    if not results:
        return pd.DataFrame()
    rows = [r.to_dict() for r in results]
    df = pd.DataFrame(rows)
    if "score" in df.columns:
        df.sort_values("score", ascending=False, inplace=True)
        df.reset_index(drop=True, inplace=True)
    return df
