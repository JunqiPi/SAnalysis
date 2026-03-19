"""
Yellow Team: Social Sentiment Quantitative Recon

Phase 1 data sources:
  - praw (Reddit API): r/wallstreetbets, r/stocks, r/shortsqueeze, etc.
  - ApeWisdom API: Reddit/4chan ticker mention frequency
  - Google Trends (pytrends): search volume spikes
  - VADER sentiment: rule-based sentiment scoring

Scoring model (0-100):
  - Mention Frequency  (0-25): Raw mention count, trending rank, spike detection
  - Sentiment Polarity (0-25): Bullish/bearish ratio, avg sentiment, consensus
  - Momentum / Trend   (0-25): Google Trends score, mention acceleration
  - Quality Signals    (0-25): Source diversity, account quality, anti-bot score
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests

from src.core.base import BaseScreener
from src.core.cache import cache_json, load_cached_json
from src.core.data_types import ScreenResult, SentimentSnapshot
from src.utils import market_data

logger = logging.getLogger(__name__)

# VADER sentiment
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _VADER = SentimentIntensityAnalyzer()
    _HAS_VADER = True
except ImportError:
    _VADER = None
    _HAS_VADER = False
    logger.warning("vaderSentiment not installed; sentiment scoring disabled.")

# Reddit (praw)
try:
    import praw
    _HAS_PRAW = True
except ImportError:
    _HAS_PRAW = False
    logger.warning("praw not installed; Reddit scanning disabled.")

# Google Trends (pytrends)
try:
    from pytrends.request import TrendReq
    _HAS_PYTRENDS = True
except ImportError:
    _HAS_PYTRENDS = False
    logger.warning("pytrends not installed; Google Trends scanning disabled.")

# Common ticker pattern for extracting $TICKER or uppercase 2-5 letter words
_TICKER_RE = re.compile(r'\$([A-Z]{1,5})\b|(?<!\w)([A-Z]{2,5})(?!\w)')

# Words that look like tickers but aren't
_TICKER_BLACKLIST = frozenset({
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL",
    "CAN", "HER", "WAS", "ONE", "OUR", "OUT", "HAS", "HIS",
    "HOW", "MAN", "NEW", "NOW", "OLD", "SEE", "WAY", "WHO",
    "DID", "GOT", "LET", "SAY", "SHE", "TOO", "USE", "CEO",
    "CFO", "COO", "IPO", "SEC", "FDA", "ETF", "ATH", "ATL",
    "DD", "OG", "OP", "PM", "AM", "US", "UK", "EU", "IT",
    "GDP", "EPS", "PE", "PB", "PS", "IV", "OI", "OTM", "ITM",
    "ATM", "DTE", "IMO", "YOLO", "HODL", "FOMO", "TLDR", "TL",
    "EDIT", "LINK", "POST", "JUST", "LIKE", "VERY", "MUCH",
    "SOME", "THIS", "THAT", "WHAT", "WITH", "FROM", "THEY",
    "WILL", "BEEN", "HAVE", "EACH", "MAKE", "WHEN", "THAN",
    "THEM", "MOST", "ONLY", "OVER", "SUCH", "TAKE", "LONG",
    "ALSO", "INTO", "YEAR", "YOUR", "JUST", "MORE", "NEXT",
    "GOOD", "HIGH", "HUGE", "BIG", "LOW", "UP", "DOWN",
    "PUMP", "DUMP", "BEAR", "BULL", "HOLD", "SELL", "BUY",
    "CALL", "PUT", "MOON", "GAIN", "LOSS", "RED", "GREEN",
})


def _extract_tickers(text: str) -> list[str]:
    """Extract stock ticker symbols from text."""
    matches = _TICKER_RE.findall(text)
    tickers = set()
    for dollar_match, bare_match in matches:
        t = dollar_match or bare_match
        if t and t not in _TICKER_BLACKLIST:
            tickers.add(t)
    return list(tickers)


# Financial lexicon overlay for VADER.
# VADER misclassifies common finance terms:
#   "short" → negative (but neutral in finance: "shorting a stock")
#   "squeeze" → negative (but bullish in meme stock context)
#   "retard"/"retards" → strongly negative (but neutral/positive in WSB)
#   "calls" → neutral (but bullish in options context)
#   "puts" → neutral (but bearish in options context)
#   "dump" → negative (correct for finance)
#   "moon" → neutral (but bullish in meme context)
_FINANCIAL_LEXICON: dict[str, float] = {
    "short": 0.0,       # Neutral in finance
    "shorting": 0.0,
    "shorts": 0.0,
    "squeeze": 1.5,     # Bullish in meme context
    "squeezing": 1.0,
    "retard": 0.0,      # Neutral in WSB
    "retards": 0.0,
    "retarded": 0.0,
    "moon": 2.0,        # Strongly bullish in meme context
    "mooning": 2.5,
    "tendies": 1.5,     # WSB: profits
    "diamond": 1.0,     # "Diamond hands" = holding
    "rocket": 1.5,      # Bullish meme signal
    "ape": 0.5,         # WSB identity, mildly bullish
    "apes": 0.5,
    "calls": 0.5,       # Mildly bullish (options)
    "puts": -0.5,       # Mildly bearish (options)
    "bag": -1.0,        # "Bag holder" = negative
    "bagholder": -1.5,
    "bagholding": -1.5,
}

# Apply financial lexicon overlay to VADER instance
if _HAS_VADER and _VADER is not None:
    _VADER.lexicon.update(_FINANCIAL_LEXICON)


def _vader_score(text: str) -> float:
    """Return VADER compound sentiment score (-1 to 1).

    Uses a financial lexicon overlay to correct VADER's misclassification
    of common stock market / WSB terminology.
    """
    if not _HAS_VADER or _VADER is None:
        return 0.0
    scores = _VADER.polarity_scores(text)
    return scores["compound"]


class SocialSentimentScreener(BaseScreener):
    """Yellow Team screener: quantifies social media sentiment and momentum."""

    _reddit_warning_logged = False  # class-level flag to avoid log spam

    def __init__(self) -> None:
        super().__init__()
        # Cached praw.Reddit client (created once, reused across all tickers).
        # Avoids recreating the OAuth session per ticker in _get_reddit_sentiment.
        self._reddit_client: Optional[object] = None
        # Google Trends circuit breaker: after N consecutive failures,
        # stop trying for the remainder of this scan run.
        self._gt_consecutive_failures: int = 0
        self._gt_circuit_open: bool = False

    @property
    def team_name(self) -> str:
        return "yellow"

    def _team_cfg(self):
        return self.cfg["yellow_team"]

    def _get_reddit_client(self) -> Optional[object]:
        """Return a cached praw.Reddit instance (lazy-init, reused across tickers)."""
        if self._reddit_client is not None:
            return self._reddit_client
        if not _HAS_PRAW:
            return None
        api_keys = self.cfg.get_nested("api_keys") or {}
        client_id = api_keys.get("reddit_client_id", "")
        client_secret = api_keys.get("reddit_client_secret", "")
        if not client_id or not client_secret:
            return None
        try:
            self._reddit_client = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent=api_keys.get("reddit_user_agent", "SAnalysis/0.1"),
            )
            return self._reddit_client
        except Exception:
            logger.exception("[yellow] Failed to initialize Reddit client.")
            return None

    def _check_reddit_credentials(self) -> bool:
        """Check if Reddit API credentials are configured.

        Logs a WARNING (once) if credentials are missing, since this
        disables the sentiment_polarity scoring dimension entirely.
        """
        api_keys = self.cfg.get_nested("api_keys") or {}
        client_id = api_keys.get("reddit_client_id", "")
        client_secret = api_keys.get("reddit_client_secret", "")
        has_creds = bool(client_id and client_secret)

        if not has_creds and not SocialSentimentScreener._reddit_warning_logged:
            logger.warning(
                "[yellow] Reddit API credentials not configured! "
                "sentiment_polarity will be 0 for ALL tickers. "
                "To fix: create config/secrets.yaml with reddit_client_id "
                "and reddit_client_secret, or set REDDIT_CLIENT_ID and "
                "REDDIT_CLIENT_SECRET environment variables."
            )
            SocialSentimentScreener._reddit_warning_logged = True

        return has_creds

    # ------------------------------------------------------------------
    # Candidate discovery (via ApeWisdom trending)
    # ------------------------------------------------------------------

    def fetch_candidates(self) -> list[str]:
        """Fetch trending tickers from ApeWisdom + Reddit scan."""
        # Early credential check so the warning appears at scan start
        self._check_reddit_credentials()

        tickers: list[str] = []

        # Source 1: ApeWisdom API
        aw_tickers = self._fetch_apewisdom()
        tickers.extend(aw_tickers)

        # Source 2: Reddit scan (if praw is configured)
        reddit_tickers = self._scan_reddit_for_tickers()
        tickers.extend(reddit_tickers)

        # Deduplicate while preserving order
        seen = set()
        unique: list[str] = []
        for t in tickers:
            if t not in seen:
                seen.add(t)
                unique.append(t)

        if not unique:
            # Fallback curated list
            unique = ["GME", "AMC", "PLTR", "TSLA", "NVDA", "SOFI", "BB", "CLOV"]

        return unique

    def _fetch_apewisdom(self) -> list[str]:
        """Fetch top trending tickers from ApeWisdom API.

        Caches the FULL response data (mentions, rank, upvotes, etc.)
        so _get_apewisdom_ticker() can look up per-ticker data without
        re-fetching the same URL.
        """
        cached = load_cached_json("apewisdom", "trending_full")
        if cached is not None:
            # Full data already cached; extract ticker list
            return [r["ticker"] for r in cached if "ticker" in r]

        url = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/1"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            top_n = self._team_cfg().get("apewisdom_top_n", 50)
            top_results = results[:top_n]

            # Cache full data for all top tickers (single API call)
            enriched = []
            for i, r in enumerate(top_results, 1):
                if "ticker" not in r:
                    continue
                entry = {
                    "ticker": r["ticker"],
                    "mentions": r.get("mentions", 0),
                    "rank": i,
                    "upvotes": r.get("upvotes", 0),
                    "mentions_24h_ago": r.get("mentions_24h_ago", 0),
                }
                enriched.append(entry)
                # Also cache per-ticker for _get_apewisdom_ticker lookup
                cache_json("apewisdom", f"ticker_{r['ticker']}", entry)

            cache_json("apewisdom", "trending_full", enriched)
            tickers = [e["ticker"] for e in enriched]
            logger.info("[yellow] ApeWisdom returned %d trending tickers.", len(tickers))
            return tickers
        except Exception:
            logger.exception("[yellow] ApeWisdom API failed.")
            return []

    def _scan_reddit_for_tickers(self) -> list[str]:
        """Scan configured subreddits for ticker mentions.

        Uses cached Reddit client (created once via _get_reddit_client()).
        """
        cfg = self._team_cfg()
        reddit = self._get_reddit_client()
        if reddit is None:
            return []

        subreddits = cfg.get("subreddits", ["wallstreetbets"])
        post_limit = cfg.get("reddit_post_limit", 100)
        ticker_counts: dict[str, int] = {}

        for sub_name in subreddits:
            try:
                sub = reddit.subreddit(sub_name)
                for post in sub.hot(limit=post_limit):
                    text = f"{post.title} {post.selftext}"
                    for t in _extract_tickers(text):
                        ticker_counts[t] = ticker_counts.get(t, 0) + 1
            except Exception:
                logger.exception("[yellow] Failed to scan r/%s", sub_name)

        # Sort by mention count, return top tickers
        sorted_tickers = sorted(ticker_counts, key=ticker_counts.get, reverse=True)
        return sorted_tickers[:50]

    # ------------------------------------------------------------------
    # Per-ticker sentiment analysis
    # ------------------------------------------------------------------

    def _collect_sentiment(self, ticker: str) -> SentimentSnapshot:
        """Aggregate sentiment data for a single ticker from all sources."""
        snap = SentimentSnapshot(ticker=ticker)

        # ApeWisdom mention data
        aw_data = self._get_apewisdom_ticker(ticker)
        if aw_data:
            snap.mention_count += aw_data.get("mentions", 0)
            snap.trending_rank = aw_data.get("rank")
            snap.sources.append("apewisdom")

        # Reddit sentiment (if available)
        reddit_sentiment = self._get_reddit_sentiment(ticker)
        if reddit_sentiment:
            snap.mention_count += reddit_sentiment["count"]
            snap.avg_sentiment = reddit_sentiment["avg_sentiment"]
            snap.bullish_pct = reddit_sentiment["bullish_pct"]
            snap.bearish_pct = reddit_sentiment["bearish_pct"]
            snap.neutral_pct = reddit_sentiment["neutral_pct"]
            snap.sources.append("reddit")

        # Google Trends
        gt_score = self._get_google_trends(ticker)
        if gt_score is not None:
            snap.google_trends_score = gt_score
            snap.sources.append("google_trends")

        return snap

    def _get_apewisdom_ticker(self, ticker: str) -> Optional[dict]:
        """Get ApeWisdom data for a specific ticker.

        Relies on per-ticker cache populated by _fetch_apewisdom().
        No redundant API calls — if the ticker wasn't in the trending list,
        it simply returns None (not trending = no ApeWisdom signal).
        """
        cached = load_cached_json("apewisdom", f"ticker_{ticker}")
        if cached is not None:
            return cached

        # If per-ticker cache miss, check the full trending cache
        full = load_cached_json("apewisdom", "trending_full")
        if full is not None:
            for entry in full:
                if entry.get("ticker") == ticker:
                    cache_json("apewisdom", f"ticker_{ticker}", entry)
                    return entry

        # Not in ApeWisdom trending — no signal
        return None

    def _get_reddit_sentiment(self, ticker: str) -> Optional[dict]:
        """Compute sentiment from Reddit posts mentioning this ticker.

        Uses cached scan results if available, otherwise falls back
        to a targeted search via the cached Reddit client.
        """
        cached = load_cached_json("reddit_sentiment", ticker)
        if cached is not None:
            return cached

        if not _HAS_VADER:
            return None

        reddit = self._get_reddit_client()
        if reddit is None:
            return None

        cfg = self._team_cfg()
        min_score = cfg.get("reddit_min_score", 10)
        sentiments: list[float] = []
        count = 0

        for sub_name in ["wallstreetbets", "stocks", "shortsqueeze"]:
            try:
                sub = reddit.subreddit(sub_name)
                for post in sub.search(ticker, sort="hot", time_filter="week", limit=30):
                    if post.score < min_score:
                        continue
                    text = f"{post.title} {post.selftext}"
                    if ticker in _extract_tickers(text):
                        sentiments.append(_vader_score(text))
                        count += 1
            except Exception:
                continue

        if not sentiments:
            return None

        avg = sum(sentiments) / len(sentiments)
        bullish_threshold = cfg.get("sentiment_bullish_threshold", 0.3)
        bearish_threshold = cfg.get("sentiment_bearish_threshold", -0.3)

        bullish = sum(1 for s in sentiments if s >= bullish_threshold) / len(sentiments)
        bearish = sum(1 for s in sentiments if s <= bearish_threshold) / len(sentiments)
        neutral = 1.0 - bullish - bearish

        result = {
            "count": count,
            "avg_sentiment": avg,
            "bullish_pct": bullish,
            "bearish_pct": bearish,
            "neutral_pct": neutral,
        }
        cache_json("reddit_sentiment", ticker, result)
        return result

    # Circuit breaker: stop hitting Google Trends after this many consecutive failures.
    # Prevents cascade timeouts when Google rate-limits us (common with >10 queries).
    _GT_MAX_CONSECUTIVE_FAILURES = 3

    def _get_google_trends(self, ticker: str) -> Optional[float]:
        """Get Google Trends interest score for the ticker.

        Includes a circuit breaker: after _GT_MAX_CONSECUTIVE_FAILURES
        consecutive failures, all subsequent calls for this scan run
        return None immediately. This prevents cascade timeouts when
        Google rate-limits our requests.
        """
        if not _HAS_PYTRENDS:
            return None

        # Circuit breaker: skip if too many recent failures
        if self._gt_circuit_open:
            return None

        cached = load_cached_json("gtrends", ticker)
        if cached is not None:
            # Successful cache hit resets the failure counter
            self._gt_consecutive_failures = 0
            return cached

        cfg = self._team_cfg()
        try:
            pytrends = TrendReq(hl="en-US", tz=360)
            # Search for "$TICKER stock" to reduce noise
            kw = f"{ticker} stock"
            pytrends.build_payload(
                [kw],
                timeframe=cfg.get("google_trends_timeframe", "now 7-d"),
                geo=cfg.get("google_trends_geo", "US"),
            )
            df = pytrends.interest_over_time()
            if df.empty:
                return None

            # Return the most recent interest value (0-100 scale)
            score = float(df[kw].iloc[-1])
            cache_json("gtrends", ticker, score)
            self._gt_consecutive_failures = 0  # Reset on success
            return score
        except Exception:
            self._gt_consecutive_failures += 1
            if self._gt_consecutive_failures >= self._GT_MAX_CONSECUTIVE_FAILURES:
                self._gt_circuit_open = True
                logger.warning(
                    "[yellow] Google Trends circuit breaker OPEN after %d "
                    "consecutive failures. Skipping GT for remaining tickers.",
                    self._gt_consecutive_failures,
                )
            else:
                logger.debug("[yellow] Google Trends failed for %s (%d/%d before circuit break)",
                             ticker, self._gt_consecutive_failures, self._GT_MAX_CONSECUTIVE_FAILURES)
            return None

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_mention_frequency(self, snap: SentimentSnapshot) -> float:
        """Score 0-25: How much is this ticker being discussed?

        Measures the *absolute level* of social media attention.
        Google Trends is scored in _score_momentum (acceleration) to avoid
        double-counting.
        """
        score = 0.0

        # Raw mention count (ApeWisdom + Reddit combined)
        mc = snap.mention_count
        if mc >= 500:
            score += 12.0
        elif mc >= 200:
            score += 9.0
        elif mc >= 100:
            score += 7.0
        elif mc >= 50:
            score += 5.0
        elif mc >= 10:
            score += 3.0

        # Trending rank on ApeWisdom (independent of mention count)
        rank = snap.trending_rank
        if rank is not None:
            if rank <= 5:
                score += 13.0
            elif rank <= 10:
                score += 9.0
            elif rank <= 20:
                score += 5.0
            elif rank <= 50:
                score += 3.0

        return min(25.0, score)

    def _score_sentiment_polarity(self, snap: SentimentSnapshot) -> float:
        """Score 0-25: Sentiment direction and strength."""
        score = 0.0

        # Average sentiment
        avg = snap.avg_sentiment
        if avg >= 0.5:
            score += 10.0
        elif avg >= 0.3:
            score += 8.0
        elif avg >= 0.1:
            score += 5.0
        elif avg <= -0.3:
            score += 2.0  # Extremely bearish = potential contrarian signal
        elif avg <= -0.1:
            score += 1.0

        # Bullish consensus
        if snap.bullish_pct >= 0.7:
            score += 10.0
        elif snap.bullish_pct >= 0.5:
            score += 7.0
        elif snap.bullish_pct >= 0.3:
            score += 4.0

        # Bearish minority (some bearish = healthy, extreme = risk)
        if 0.1 <= snap.bearish_pct <= 0.3:
            score += 5.0  # Healthy debate: not pure echo chamber

        return min(25.0, score)

    def _score_momentum(self, snap: SentimentSnapshot) -> float:
        """Score 0-25: Is sentiment *accelerating*?

        Unlike mention_frequency (static level), momentum measures the
        *rate of change* in attention and sentiment.
        """
        score = 0.0

        # Google Trends score — only counted here (not in mention_frequency)
        # to avoid double-counting. GT reflects search interest momentum.
        gt = snap.google_trends_score
        if gt is not None:
            if gt >= 90:
                score += 12.0  # Parabolic interest
            elif gt >= 70:
                score += 8.0
            elif gt >= 50:
                score += 5.0
            elif gt >= 25:
                score += 2.0

        # Mention acceleration: compare current mentions vs 24h ago
        # (available from ApeWisdom data cached by _fetch_apewisdom)
        aw_data = self._get_apewisdom_ticker(snap.ticker)
        if aw_data is not None:
            current = aw_data.get("mentions") or 0
            prev = aw_data.get("mentions_24h_ago") or 0
            if prev > 0:
                acceleration = (current - prev) / prev
                if acceleration >= 2.0:
                    score += 13.0  # 3x+ surge = explosive momentum
                elif acceleration >= 1.0:
                    score += 9.0   # Doubling
                elif acceleration >= 0.5:
                    score += 5.0   # 50% increase
                elif acceleration >= 0.2:
                    score += 2.0   # Moderate growth
                elif acceleration <= -0.5:
                    score += 0.0   # Fading fast
            elif current > 0:
                # Newly trending (was zero yesterday)
                score += 10.0

        return min(25.0, score)

    def _score_quality(self, snap: SentimentSnapshot) -> float:
        """Score 0-25: Data quality and signal reliability.

        Source diversity scoring is calibrated so that ApeWisdom alone
        (no Reddit API) can still achieve a reasonable quality score
        when the data is otherwise strong. The penalty for missing Reddit
        is already applied in sentiment_polarity (0/25).
        """
        score = 0.0

        # Source diversity: more sources = higher confidence
        n_sources = len(snap.sources)
        if n_sources >= 3:
            score += 10.0
        elif n_sources >= 2:
            score += 7.0
        elif n_sources >= 1:
            score += 4.0  # Single source but still valid signal

        # Sample size (mention count as proxy for data reliability)
        if snap.mention_count >= 100:
            score += 8.0
        elif snap.mention_count >= 50:
            score += 6.0
        elif snap.mention_count >= 20:
            score += 4.0
        elif snap.mention_count >= 5:
            score += 2.0

        # Sentiment balance (requires Reddit data to be meaningful)
        if snap.bullish_pct > 0:  # Only evaluate if we have sentiment data
            if 0.2 <= snap.bullish_pct <= 0.8:
                score += 7.0  # Balanced discussion
            elif snap.bullish_pct > 0.8:
                score += 3.0  # Echo chamber penalty

        return min(25.0, score)

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    def analyze(self, ticker: str) -> ScreenResult | None:
        """Full sentiment analysis for a single ticker."""
        snap = self._collect_sentiment(ticker)

        # Must have at least some data
        if snap.mention_count == 0 and snap.google_trends_score is None:
            return None

        # Market cap gate: social sentiment is most actionable for small caps
        # that can actually achieve explosive moves
        info = market_data.get_ticker_info(snap.ticker)
        mcap = info.get("marketCap") if info else None
        max_mcap = self._team_cfg().get("max_market_cap_millions", 3000)
        if mcap is not None and mcap > max_mcap * 1e6:
            logger.debug(
                "[yellow] %s market cap $%.1fB exceeds max $%.1fB, skipping.",
                ticker, mcap / 1e9, max_mcap / 1e3,
            )
            return None

        s1 = self._score_mention_frequency(snap)
        s2 = self._score_sentiment_polarity(snap)
        s3 = self._score_momentum(snap)
        s4 = self._score_quality(snap)
        total = s1 + s2 + s3 + s4

        return ScreenResult(
            ticker=ticker,
            team="yellow",
            score=total,
            signals={
                "mention_frequency": s1,
                "sentiment_polarity": s2,
                "sentiment_momentum": s3,
                "signal_quality": s4,
                "mention_count": float(snap.mention_count),
                "avg_sentiment": snap.avg_sentiment,
                "bullish_pct": snap.bullish_pct,
                "bearish_pct": snap.bearish_pct,
                "google_trends": snap.google_trends_score or 0,
            },
            metadata={
                "trending_rank": snap.trending_rank,
                "market_cap_millions": mcap / 1e6 if mcap else None,
                "sources": snap.sources,
            },
        )
