"""
Finviz free-tier screener scraper.

Fetches screener results by constructing filter URLs and parsing
the HTML table. Respects rate limits with delays between requests.

NOTE: Finviz free tier has 15-minute delayed data. This is acceptable
for Phase 1 paper-trading validation.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from src.core.config import get_config

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 30

_BASE_URL = "https://finviz.com/screener.ashx"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Finviz filter codes for common screens
FILTER_MAP = {
    # Short float
    "short_float_over5": "sh_short_o5",
    "short_float_over10": "sh_short_o10",
    "short_float_over15": "sh_short_o15",
    "short_float_over20": "sh_short_o20",
    "short_float_over25": "sh_short_o25",
    "short_float_over30": "sh_short_o30",
    # Average volume
    "avg_vol_over100k": "sh_avgvol_o100",
    "avg_vol_over200k": "sh_avgvol_o200",
    "avg_vol_over500k": "sh_avgvol_o500",
    # Price
    "price_over1": "sh_price_o1",
    "price_over5": "sh_price_o5",
    "price_1to10": "sh_price_u10o1",
    "price_1to50": "sh_price_u50o1",
    # Market cap
    "cap_smallunder2b": "cap_smallunder",
    "cap_midover2b": "cap_midover",
    "cap_micro": "cap_micro",
    # Float
    "float_under10m": "sh_float_u10",
    "float_under20m": "sh_float_u20",
    "float_under50m": "sh_float_u50",
    "float_under100m": "sh_float_u100",
    # Relative volume
    "rvol_over1.5": "sh_relvol_o1.5",
    "rvol_over2": "sh_relvol_o2",
    "rvol_over3": "sh_relvol_o3",
    # Performance
    "perf_today_up": "ta_perf_dup",
    "perf_today_up5": "ta_perf_d5u",
    "perf_today_up10": "ta_perf_d10u",
    # RSI
    "rsi_oversold30": "ta_rsi_os30",
    "rsi_overbought70": "ta_rsi_ob70",
}

# Column view mode: custom columns that include short float
_CUSTOM_VIEW = "152"  # Valuation + short float columns


def _parse_screener_table(html: str) -> pd.DataFrame:
    """Parse the Finviz screener results table into a DataFrame."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="screener_table")
    if table is None:
        # Fallback: look for table by id
        table = soup.find("table", {"id": "screener-views-table"})
    if table is None:
        logger.warning("Could not locate screener table in HTML response.")
        return pd.DataFrame()

    rows = table.find_all("tr")
    if len(rows) < 2:
        return pd.DataFrame()

    headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
    data = []
    for row in rows[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) == len(headers):
            data.append(cells)

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data, columns=headers)
    return df


def _clean_numeric(series: pd.Series) -> pd.Series:
    """Strip %, B, M, K suffixes and convert to float."""
    def _parse(val: str) -> float | None:
        if not val or val == "-":
            return None
        val = val.strip()
        multiplier = 1.0
        if val.endswith("%"):
            val = val[:-1]
        if val.endswith("B"):
            val = val[:-1]
            multiplier = 1e9
        elif val.endswith("M"):
            val = val[:-1]
            multiplier = 1e6
        elif val.endswith("K"):
            val = val[:-1]
            multiplier = 1e3
        try:
            return float(val.replace(",", "")) * multiplier
        except ValueError:
            return None

    return series.apply(_parse)


def screen(filters: list[str], max_pages: int = 3) -> pd.DataFrame:
    """Run a Finviz screener with the given filter codes.

    Args:
        filters: List of Finviz filter codes (e.g. ['sh_short_o10', 'sh_avgvol_o200']).
        max_pages: Maximum result pages to fetch (20 results per page).

    Returns:
        DataFrame with screener results. Columns vary by view mode.
    """
    all_dfs: list[pd.DataFrame] = []
    filter_str = ",".join(filters)

    for page_idx in range(max_pages):
        start = page_idx * 20 + 1
        params: dict[str, Any] = {
            "v": _CUSTOM_VIEW,
            "f": filter_str,
            "r": str(start),
        }
        try:
            timeout = get_config().get_nested(
                "general", "network_timeout_seconds",
                default=_DEFAULT_TIMEOUT_SECONDS,
            )
            resp = requests.get(_BASE_URL, params=params, headers=_HEADERS, timeout=timeout)
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception("Finviz request failed (page %d)", page_idx + 1)
            break

        df = _parse_screener_table(resp.text)
        if df.empty:
            break
        all_dfs.append(df)

        # Stop if we got fewer than a full page
        if len(df) < 20:
            break

        # Polite delay between pages
        time.sleep(1.5)

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    # Deduplicate by ticker
    ticker_col = "Ticker" if "Ticker" in combined.columns else combined.columns[1]
    combined.drop_duplicates(subset=[ticker_col], keep="first", inplace=True)
    return combined


def get_short_squeeze_candidates(
    min_short_float: str = "over10",
    min_avg_volume: str = "over200k",
    min_price: str = "over1",
) -> pd.DataFrame:
    """Convenience: fetch stocks with high short float for Red Team.

    Returns a DataFrame with ticker, short float %, float shares, etc.
    """
    filter_codes = []

    # Map friendly names to filter codes
    sf_map = {
        "over5": "sh_short_o5",
        "over10": "sh_short_o10",
        "over15": "sh_short_o15",
        "over20": "sh_short_o20",
        "over25": "sh_short_o25",
        "over30": "sh_short_o30",
    }
    vol_map = {
        "over100k": "sh_avgvol_o100",
        "over200k": "sh_avgvol_o200",
        "over500k": "sh_avgvol_o500",
    }
    price_map = {
        "over1": "sh_price_o1",
        "over5": "sh_price_o5",
    }

    filter_codes.append(sf_map.get(min_short_float, "sh_short_o10"))
    filter_codes.append(vol_map.get(min_avg_volume, "sh_avgvol_o200"))
    filter_codes.append(price_map.get(min_price, "sh_price_o1"))

    return screen(filter_codes)


def get_low_float_candidates(
    max_float: str = "under50m",
    min_rvol: str = "over2",
    min_price: str = "over1",
) -> pd.DataFrame:
    """Convenience: fetch low-float high-RVOL stocks for Green Team."""
    float_map = {
        "under10m": "sh_float_u10",
        "under20m": "sh_float_u20",
        "under50m": "sh_float_u50",
        "under100m": "sh_float_u100",
    }
    rvol_map = {
        "over1.5": "sh_relvol_o1.5",
        "over2": "sh_relvol_o2",
        "over3": "sh_relvol_o3",
    }
    price_map = {
        "over1": "sh_price_o1",
        "over5": "sh_price_o5",
    }

    codes = [
        float_map.get(max_float, "sh_float_u50"),
        rvol_map.get(min_rvol, "sh_relvol_o2"),
        price_map.get(min_price, "sh_price_o1"),
    ]
    return screen(codes)


def get_small_cap_momentum_candidates(
    max_cap: str = "smallunder2b",
    min_rvol: str = "over1.5",
    min_price: str = "over1",
    min_avg_volume: str = "over200k",
) -> pd.DataFrame:
    """Convenience: fetch small-cap stocks with momentum signals for Blue Team.

    Targets stocks under $2B market cap with elevated relative volume,
    indicating potential momentum setups.
    """
    cap_map = {
        "micro": "cap_micro",
        "smallunder2b": "cap_smallunder",
        "small": "cap_small",
    }
    rvol_map = {
        "over1.5": "sh_relvol_o1.5",
        "over2": "sh_relvol_o2",
        "over3": "sh_relvol_o3",
    }
    vol_map = {
        "over100k": "sh_avgvol_o100",
        "over200k": "sh_avgvol_o200",
        "over500k": "sh_avgvol_o500",
    }
    price_map = {
        "over1": "sh_price_o1",
        "over5": "sh_price_o5",
    }

    codes = [
        cap_map.get(max_cap, "cap_smallunder"),
        rvol_map.get(min_rvol, "sh_relvol_o1.5"),
        vol_map.get(min_avg_volume, "sh_avgvol_o200"),
        price_map.get(min_price, "sh_price_o1"),
    ]
    return screen(codes)
