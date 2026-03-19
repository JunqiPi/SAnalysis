"""
Finviz free-tier screener scraper.

Fetches screener results by constructing filter URLs and parsing
the HTML table. Respects rate limits with delays between requests.

NOTE: Finviz free tier has 15-minute delayed data. This is acceptable
for Phase 1 paper-trading validation.

IMPORTANT: Finviz free tier ignores the ``o=`` (order_by) URL parameter,
always returning results in alphabetical ticker order.  To ensure the
most relevant candidates appear first (not just A-C tickers), each
convenience function selects a Finviz *view* that contains the target
sort column and applies **client-side sorting** after fetching.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from src.core.cache import cache_json, load_cached_json
from src.core.config import get_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Finviz view IDs — each view exposes a different column set.
# Choosing the right view is critical for client-side sorting because
# you can only sort by columns that are actually present in the response.
# ---------------------------------------------------------------------------
VIEW_OVERVIEW = "111"      # Ticker, Company, Sector, Industry, Country, Market Cap, P/E, Price, Change, Volume
VIEW_OWNERSHIP = "131"     # Market Cap, Outstanding, Float, Insider Own, Inst Own, Short Float, Short Ratio, ...
VIEW_PERFORMANCE = "141"   # Perf Week..10Y, Volatility W/M, Avg Volume, Rel Volume, Price, Change, Volume
VIEW_CUSTOM = "152"        # Valuation + short float columns (legacy default)
VIEW_FINANCIAL = "161"     # Market Cap, ROA, ROE, ROIC, Debt/Eq, Margins, Earnings, ...

# Finviz sort column identifiers for the ``o=`` URL parameter.
# Retained for forward-compatibility (Elite/Pro tiers support server-side sorting).
# Prefix with ``-`` for descending order; ascending is the default.
ORDER_SHORT_FLOAT_DESC = "-shortfloat"  # Highest short float first
ORDER_RVOL_DESC = "-relativevolume"     # Highest relative volume first
ORDER_MARKET_CAP_ASC = "marketcap"      # Smallest market cap first
ORDER_FLOAT_ASC = "float"              # Smallest float first
ORDER_CHANGE_DESC = "-change"           # Biggest movers first
ORDER_VOLUME_DESC = "-volume"           # Highest volume first

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


def sort_dataframe(
    df: pd.DataFrame,
    sort_column: str,
    ascending: bool = True,
) -> pd.DataFrame:
    """Sort a Finviz DataFrame by a numeric column (client-side).

    Parses the column with ``_clean_numeric()``, sorts, then drops
    the temporary sort key.  Rows where the sort column is missing
    or unparseable are pushed to the bottom.

    Args:
        df: Finviz screener DataFrame.
        sort_column: Column name to sort by (must exist in *df*).
        ascending: Sort direction; False = highest first.

    Returns:
        Sorted DataFrame (new object, original unchanged).
    """
    if df.empty or sort_column not in df.columns:
        return df

    sorted_df = df.copy()
    sort_key = f"_sort_{sort_column}"
    sorted_df[sort_key] = _clean_numeric(sorted_df[sort_column])
    sorted_df.sort_values(
        sort_key, ascending=ascending, na_position="last", inplace=True,
    )
    sorted_df.drop(columns=[sort_key], inplace=True)
    sorted_df.reset_index(drop=True, inplace=True)
    return sorted_df


def screen(
    filters: list[str],
    max_pages: int = 10,
    order_by: str | None = None,
    view: str = VIEW_CUSTOM,
) -> pd.DataFrame:
    """Run a Finviz screener with the given filter codes.

    Args:
        filters: List of Finviz filter codes (e.g. ['sh_short_o10', 'sh_avgvol_o200']).
        max_pages: Maximum result pages to fetch (20 results per page).
            Default 10 (200 results).  First run takes ~15s (1.5s polite
            delay per page) but results are cached for 1 hour.
        order_by: Finviz sort column for the ``o=`` URL parameter.
            Prefix with ``-`` for descending.  **NOTE**: This is ignored
            by the Finviz free tier; the convenience functions apply
            client-side sorting instead.  Retained for forward-compatibility
            with Elite/Pro tiers.
        view: Finviz view ID controlling which columns are returned.
            Use the ``VIEW_*`` constants.  Different views expose different
            columns — choose the view that contains the column you need
            for client-side sorting.

    Returns:
        DataFrame with screener results. Columns vary by view mode.
    """
    filter_str = ",".join(sorted(filters))
    cache_key = f"{filter_str}|{order_by or ''}|v{view}|p{max_pages}"

    # Check cache first (Finviz free tier is 15-min delayed; 1-hour cache
    # avoids redundant HTTP calls on repeated runs).
    cached = load_cached_json("finviz_screen", cache_key, ttl_seconds=3600)
    if cached is not None:
        df = pd.DataFrame(cached)
        logger.debug(
            "Finviz screen cache hit (%d rows): filters=%s order=%s view=%s",
            len(df), filter_str, order_by, view,
        )
        return df

    all_dfs: list[pd.DataFrame] = []

    for page_idx in range(max_pages):
        start = page_idx * 20 + 1
        params: dict[str, Any] = {
            "v": view,
            "f": filter_str,
            "r": str(start),
        }
        if order_by:
            params["o"] = order_by

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

    # Cache the results (store as list-of-dicts for JSON serialization)
    try:
        cache_json("finviz_screen", cache_key, combined.to_dict(orient="records"))
    except Exception:
        logger.debug("Failed to cache Finviz screen results.", exc_info=True)

    return combined


def get_short_squeeze_candidates(
    min_short_float: str = "over10",
    min_avg_volume: str = "over200k",
    min_price: str = "over1",
) -> pd.DataFrame:
    """Convenience: fetch stocks with high short float for Red Team.

    Uses Finviz view 131 (Ownership) which exposes "Short Float" and
    "Short Ratio" columns, then sorts client-side by short float
    descending so the most heavily shorted stocks appear first.

    Returns a DataFrame with ticker, short float %, float shares, etc.
    """
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

    filter_codes = [
        sf_map.get(min_short_float, "sh_short_o10"),
        vol_map.get(min_avg_volume, "sh_avgvol_o200"),
        price_map.get(min_price, "sh_price_o1"),
    ]

    df = screen(
        filter_codes,
        order_by=ORDER_SHORT_FLOAT_DESC,
        view=VIEW_OWNERSHIP,
    )
    # Client-side sort: highest short float first
    return sort_dataframe(df, "Short Float", ascending=False)


def get_low_float_candidates(
    max_float: str = "under50m",
    min_rvol: str = "over2",
    min_price: str = "over1",
) -> pd.DataFrame:
    """Convenience: fetch low-float high-RVOL stocks for Green Team.

    Uses Finviz view 141 (Performance) which exposes "Rel Volume",
    then sorts client-side by relative volume descending so the
    most actively traded low-float stocks appear first.
    """
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

    df = screen(
        codes,
        order_by=ORDER_RVOL_DESC,
        view=VIEW_PERFORMANCE,
    )
    # Client-side sort: highest relative volume first
    return sort_dataframe(df, "Rel Volume", ascending=False)


def get_small_cap_momentum_candidates(
    max_cap: str = "smallunder2b",
    min_rvol: str = "over1.5",
    min_price: str = "over1",
    min_avg_volume: str = "over200k",
) -> pd.DataFrame:
    """Convenience: fetch small-cap stocks with momentum signals for Blue Team.

    Uses Finviz view 141 (Performance) which exposes "Rel Volume",
    then sorts client-side by relative volume descending to surface
    stocks with unusual activity.

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

    df = screen(
        codes,
        order_by=ORDER_RVOL_DESC,
        view=VIEW_PERFORMANCE,
    )
    # Client-side sort: highest relative volume first
    return sort_dataframe(df, "Rel Volume", ascending=False)
