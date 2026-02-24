# SDE-Team Memory

## Project: SAnalysis (Meme Stock Analysis Platform)
- Root: `/root/Pi/SAnalysis`
- Python 3.12, venv at `.venv/`
- **v0.4.0** (2026-02-24): P1 scoring refinement & robustness improvements
- Git on `main` branch (3 commits: v0.2.0, v0.3.0, v0.4.0)

## Architecture
- Layered: `src/core/` -> `src/utils/` -> `src/teams/{red,orange,yellow,green,blue}/` -> `src/pipeline/` -> `main.py`
- Config: `config/default.yaml` (YAML-driven, all thresholds configurable)
- Cache: File-based parquet/JSON in `data/cache/`, atomic writes via `_atomic_write()`, configurable TTL
- Data interface: All teams produce `ScreenResult` dataclass, orchestrator merges into DataFrame
- Base class: `BaseScreener` with `fetch_candidates()` + `analyze(ticker)` contract
- Exceptions: `src/core/exceptions.py` (SAnalysisError hierarchy; TickerValidationError inherits both SAnalysisError and ValueError)
- Lazy loading: Orchestrator uses dynamic import registry (`_SCREENER_REGISTRY` module-level), only instantiates requested teams

## Key Files
- Entry: `main.py` (CLI with --teams, --tickers, --top, --no-parallel, --version, --clear-cache, --no-save)
- Config: `src/core/config.py` (thread-safe singleton, YAML + env var merge)
- Cache: `src/core/cache.py` (atomic writes with fd_closed flag, DRY _atomic_write, clear_cache())
- Types: `src/core/data_types.py` (ScreenResult with `dict[str, Any]` metadata, timezone-aware timestamps)
- Exceptions: `src/core/exceptions.py` (SAnalysisError -> ConfigError, DataFetchError, CacheError, ScreenerError, TickerValidationError)
- Base: `src/core/base.py` (validate_ticker raises TickerValidationError, timing, dedup)
- Market data: `src/utils/market_data.py` (yfinance wrapper with ticker object reuse, no unused imports)
- Technical: `src/utils/technical.py` (pandas_ta with manual fallbacks, vectorized S/R)
- Finviz: `src/utils/finviz_scraper.py` (HTML parser for free tier)
- Pipeline: `src/pipeline/orchestrator.py` (lazy loading, per-team timing)

## Scoring
- Each team: 4 factors x 25 points = 100 max per team
- Composite: weighted average across teams (yellow weighted 0.8, blue 0.9, others 1.0)

## v0.3.0 Key Changes
- **Orange**: GEX sign: `net_gex > 0` = dealers short gamma = squeeze-prone = HIGH score. _estimate_gex is vectorized (no iterrows). _find_gex_flip uses cumulative GEX. _detect_unusual_activity takes `spot` param for OTM definition.
- **Blue**: Momentum normalization: `max(0, min(100, ret + 50))` (symmetric, 0%=50). Revenue growth ONLY in _score_financial_quality (NOT in _score_catalyst). lookback_months=14. min_momentum_score gate in analyze(). Earnings dates sorted ascending.
- **Red**: _score_catalyst and _score_technical both take `hist` param (pre-fetched in analyze()). SI capped at 100%. P/C ratio requires min 100 total volume. Stale tickers removed.
- **Green**: analyze() fetches hist once, passes to _build_snapshot_from_hist() and _score_breakout_quality(). Support/resistance uses hist.tail(63). SPAC filter has 7 industries. Float-unknown default = 2.0.
- **Yellow**: _fetch_apewisdom caches full response (trending_full). _get_apewisdom_ticker looks up from cache. VADER has financial lexicon overlay (_FINANCIAL_LEXICON dict). _score_mention_frequency = absolute level (mentions + rank). _score_momentum = acceleration (GT score + mention change rate). No double-counting.

## v0.4.0 Key Changes (IMPORTANT for future edits)
- **Red**: ShortData.as_of populated from `dateShortInterest`. Config gates enforced: min_days_to_cover=3, max_market_cap_millions=10000. _score_short_intensity uses piecewise linear interpolation (_SI_BREAKPOINTS). Signals use NaN for missing data. Finviz empty → warning log.
- **Blue**: _score_financial_quality baseline=5pts (meme-stock friendly). analyze() applies regime_multiplier (VIX≥35: 0.5x, VIX≥25: 0.7x) to total score. regime_multiplier in metadata.
- **Green**: _score_technical_setup(snap, hist) now includes MACD (fresh crossover=4, ongoing=2). _score_volume_explosion(snap, hist) verifies price direction (decline >3%: 0.3x, mild decline: 0.6x).
- **Yellow**: __init__() creates _reddit_client cache + GT circuit breaker state. _get_reddit_client() lazy-inits praw once. _GT_MAX_CONSECUTIVE_FAILURES=3 opens circuit. _get_google_trends checks _gt_circuit_open.
- **Orange**: OptionsSnapshot.put_call_ratio_oi field added. _score_gex uses magnitude normalization (imbalance = |net|/total, 3-tier: ≥0.7→14, ≥0.4→11, else→8). _score_oi_setup uses OI-weighted PCR. GEX flip scored by distance to spot.

## Dependencies
- yfinance, pandas, numpy, pandas_ta, pyyaml, requests, beautifulsoup4, lxml
- vaderSentiment, pytrends, plotly, matplotlib, pyarrow
- Optional: praw (needs Reddit API keys, moved to [reddit] extra)

## Team ↔ Code ↔ Agent Mapping
| Color | Python Class | File | Config Key | Agent |
|-------|-------------|------|-----------|-------|
| red | ShortSqueezeScreener | src/teams/red/screener.py | red_team | short-squeeze-sniper |
| orange | GammaSqueezeScreener | src/teams/orange/screener.py | orange_team | gamma-flow-hunter |
| yellow | SocialSentimentScreener | src/teams/yellow/screener.py | yellow_team | social-sentiment-quant |
| green | LowFloatBreakoutScreener | src/teams/green/screener.py | green_team | low-float-breakout |
| blue | MomentumCatalystScreener | src/teams/blue/screener.py | blue_team | momentum-catalyst-fusion |

## Remaining Known Issues (P2, not yet fixed)
- Red: scoring thresholds still hardcoded (not from config), _collect_short_data double-calls get_ticker_info, no ADR data confidence flagging
- Orange: only single expiry analyzed, no IV Rank/Percentile, 0DTE Vol/OI handling, _oi_concentration_proxy still basic
- Yellow: ticker regex false positives (e.g., "CEO" variants), bot filter config (min_account_age, min_karma) unused, per-namespace cache TTL
- Green: no reverse split detection, no dynamic consolidation thresholds, MACD not in docstring metadata output
- Blue: ADX/relative strength not used, Jegadeesh-Titman skip-recent-month not implemented, market_regime doesn't differentiate individual stocks

## Environment Notes
- Ubuntu 24.04 on WSL2, Python 3.12.3
- Must use venv (externally-managed-environment restriction)
- Activate: `source /root/Pi/SAnalysis/.venv/bin/activate`
