# SAnalysis — Meme Stock Analysis Platform

Rule 0: Ask me questions until you are 95% and up confident that you have understand my intention and goal

> v1.0.0 (2026-03-18) · 10x Monster Stock Focus Overhaul
> Python 3.12 · venv at `.venv/` · Ubuntu 24.04 / WSL2

## Quick Start

```bash
source /root/Pi/SAnalysis/.venv/bin/activate
python main.py                          # Run all 6 teams
python main.py --teams red green        # Run specific teams
python main.py --tickers GME AMC TSLA   # Analyze specific tickers
python main.py --no-parallel            # Sequential mode (debug)
python main.py --top 30                 # Show top 30 results
python main.py --ai-rescore             # Enable AI qualitative re-scoring
ANTHROPIC_API_KEY=sk-ant-... python main.py --ai-rescore --teams red  # AI + specific team
```

## Architecture

```
src/
├── core/
│   ├── base.py          # BaseScreener: fetch_candidates() + analyze(ticker) contract
│   ├── config.py        # Singleton YAML + env var config loader
│   ├── cache.py         # File-based parquet/JSON cache with TTL
│   ├── data_types.py    # ScreenResult, ShortData, OptionsSnapshot, etc.
│   └── exceptions.py    # Custom exception hierarchy (SAnalysisError, AIRescoreError, etc.)
├── ai/                  # ← NEW in v0.5.0: Claude AI re-scoring module
│   ├── __init__.py
│   ├── client.py        # Anthropic SDK wrapper (thread-safe singleton, retry, graceful degradation)
│   ├── data_types.py    # AIRescoreResult dataclass
│   └── prompts.py       # Team-specific system prompts + message builder
├── utils/
│   ├── market_data.py   # Centralized yfinance wrapper (cached)
│   ├── technical.py     # pandas_ta with manual fallbacks (RSI, MACD, BB, OBV, VWAP, ATR)
│   └── finviz_scraper.py# HTML parser for Finviz free tier
├── teams/               # ← Each team is a BaseScreener subclass
│   ├── red/screener.py
│   ├── orange/screener.py
│   ├── yellow/screener.py
│   ├── green/screener.py
│   ├── blue/screener.py
│   └── purple/screener.py  # ← NEW in v1.0.0: 10x potential structural assessor
├── pipeline/
│   └── orchestrator.py  # ThreadPoolExecutor, merge, weighted composite, resonance detection, AI re-scoring
└── main.py              # CLI entry point
```

## Team ↔ Code ↔ Agent Mapping (CRITICAL)

| Color | Python Class | File | Config Key | Claude Agent | Scoring Factors (4×25=100) |
|-------|-------------|------|-----------|-------------|---------------------------|
| 🔴 Red | `ShortSqueezeScreener` | `src/teams/red/screener.py` | `red_team` | `short-squeeze-sniper` | short_intensity, cover_difficulty, catalyst_proximity, technical_momentum |
| 🟠 Orange | `GammaSqueezeScreener` | `src/teams/orange/screener.py` | `orange_team` | `gamma-flow-hunter` | options_activity, gamma_exposure, iv_dynamics, oi_setup |
| 🟡 Yellow | `SocialSentimentScreener` | `src/teams/yellow/screener.py` | `yellow_team` | `social-sentiment-quant` | mention_frequency, sentiment_polarity, sentiment_momentum, signal_quality |
| 🟢 Green | `LowFloatBreakoutScreener` | `src/teams/green/screener.py` | `green_team` | `low-float-breakout` | float_tightness, volume_explosion, technical_setup, breakout_quality |
| 🔵 Blue | `MomentumCatalystScreener` | `src/teams/blue/screener.py` | `blue_team` | `momentum-catalyst-fusion` | price_momentum, catalyst_proximity, financial_quality, market_regime |
| 🟣 Purple | `TenBaggerScreener` | `src/teams/purple/screener.py` | `purple_team` | N/A (structural only) | market_cap_tier, float_structure, dilution_risk, explosive_setup |
| 🟧 SDE-Team | N/A (code writer) | N/A | N/A | `SDE-Team` | N/A |

## Scoring Model

- Each team: 4 factors × 25 points = **100 max per team**
- All teams output `ScreenResult` dataclass (defined in `src/core/data_types.py`)
- Orchestrator computes weighted composite: `red×1.2, orange×1.0, yellow×0.7, green×1.2, blue×0.5, purple×1.3`
- **Market cap gates**: All teams filter out stocks above team-specific market cap ceilings (Red/Green/Blue/Purple: $2B, Yellow: $3B, Orange: $5B)
- **Resonance bonus**: When 3+ teams flag the same ticker (score > 0), a ×1.25 multiplier is applied to the composite score
- **AI Re-Scoring** (opt-in via `--ai-rescore`): `blended = quant×0.7 + ai×0.3` (configurable `ai_weight`)
- Results sorted by composite score, saved to `data/output/watchlist_YYYYMMDD_HHMMSS.csv`

## Data Interface

- All teams inherit `BaseScreener` (`src/core/base.py`)
- Contract: `fetch_candidates() → list[str]`, `analyze(ticker) → ScreenResult | None`
- `run(tickers=None)` orchestrates both; called by `PipelineOrchestrator`

## Config

- Primary: `config/default.yaml` (all thresholds configurable per team)
- Secrets: `config/secrets.yaml` (git-ignored, Reddit API keys)
- Environment variables override YAML values

## Cache

- File-based: parquet for DataFrames, JSON for dicts
- Location: `data/cache/`
- TTL: configurable (default 4 hours)

## Dependencies

yfinance, pandas, numpy, pandas_ta, pyyaml, requests, beautifulsoup4, lxml,
vaderSentiment, pytrends, plotly, matplotlib, pyarrow.
Optional: praw (Reddit API — needs keys in secrets.yaml), anthropic (AI re-scoring — needs API key)

## Agent Instructions

**Analysis Agents (6 teams)**: When asked to analyze stocks, you MUST:
1. First run the Python pipeline: `python main.py --teams <your_color>`
2. Read the output CSV from `data/output/`
3. Use the Python scoring as your quantitative foundation
4. Layer your qualitative analysis ON TOP of the code's results
5. Reference specific scoring factors and thresholds from `config/default.yaml`

**SDE-Team**: When modifying code, always:
1. Read the relevant screener file first
2. Follow the `BaseScreener` contract
3. Output `ScreenResult` dataclass
4. Update `config/default.yaml` for new thresholds
5. Update this CLAUDE.md if architecture changes

## Change Log

- **2026-02-23 v0.1.0**: Phase 1 complete. 5 teams, pipeline orchestrator, CLI.
- **2026-02-23 v0.1.1**: Agent configuration audit. Created CLAUDE.md, aligned agent colors with Python team colors, added code awareness to all agents, fixed SDE-Team description, added tools restrictions to analysis agents.
- **2026-02-24 v0.1.2**: Bug fixes from first full-pipeline analysis run.
  - Fixed `detect_breakout()` in `src/utils/technical.py`: now requires upside price direction (previously used `abs()` which caught downside crashes as breakouts).
  - Added SPAC/shell company exclusion filter in `src/teams/green/screener.py`: industry "Shell Companies" and "Blank Checks" are now filtered out.
  - Added Reddit API credential warning in `src/teams/yellow/screener.py`: logs a clear WARNING when `config/secrets.yaml` is missing, explaining that `sentiment_polarity` will be 0 for all tickers.
- **2026-02-24 v0.2.0**: Codebase maturity overhaul. Thread-safe config singleton, atomic cache writes, custom exception hierarchy, ticker validation, lazy screener loading, yfinance object reuse, vectorized S/R calculation, `--version`/`--clear-cache`/`--no-save` CLI flags, timezone-aware timestamps, metadata preservation in ScreenResult. See `Documentation/CHANGELOG.md` for full details.
- **2026-02-24 v0.3.0**: Scoring logic & data integrity overhaul. 5-team specialist agent audit identified 20 P0 issues. **Critical fix**: Orange team GEX sign convention was inverted. Blue team momentum normalization bias (0%→33.3 instead of 50), revenue double-counting. Red team stale tickers, SI validation. Green team 3x API deduplication, expanded SPAC filter. Yellow team ApeWisdom caching, VADER financial lexicon, momentum/mention double-counting fix. Core: cache.py double-close bug, DRY cache_dataframe, TickerValidationError. See `Documentation/CHANGELOG.md` for full details.
- **2026-02-24 v0.4.0**: P1 scoring refinement & robustness. **Red**: ShortData.as_of population + staleness warning, config gates enforced (min_DTC, max_mcap), piecewise linear scoring interpolation, NaN for missing signals. **Blue**: financial quality baseline (5pt floor for meme stocks), VIX regime multiplier (0.5x/0.7x total score). **Green**: MACD added to technical setup, RVOL price direction verification (crash discount). **Yellow**: Google Trends circuit breaker (3 failures → skip remaining), Reddit client caching (single praw instance per run). **Orange**: OI-weighted PCR, GEX magnitude normalization (imbalance ratio), flip point distance scoring. See `Documentation/CHANGELOG.md` for full details.
- **2026-03-17 v0.4.1**: Infrastructure hardening & scoring bugfix (5 fixes).
  - **Network timeouts**: Added `general.network_timeout_seconds` (default 30s) to config. Finviz scraper reads timeout from config instead of hardcoded value. Documented yfinance timeout limitation in `market_data.py`.
  - **Blue team D/E fix**: Negative debt-to-equity (insolvency) no longer scores as "very low debt" (was 5pts, now 0pts).
  - **Orchestrator weights to config**: Team weights moved from hardcoded `DEFAULT_TEAM_WEIGHTS` to `config/default.yaml` under `orchestrator.team_weights`. Code reads from config with 3-tier fallback (explicit arg > YAML > hardcoded).
  - **YAML parse error handling**: `config.py` now catches `yaml.YAMLError` on both `default.yaml` and `secrets.yaml`, logs the failing file path, and raises `ConfigError`.
  - **Yellow team `_score_momentum` None guard**: `aw_data.get("mentions_24h_ago")` could return explicit `None` (key present, value null), bypassing `dict.get()` default. Comparison `None > 0` raised `TypeError`. Fixed by using `or 0` coalescion on both `mentions` and `mentions_24h_ago`.
- **2026-03-17**: Added comprehensive Chinese (Simplified) user manual at `Documentation/USER_MANUAL.md`. Covers platform overview, quick start guide, detailed 5-team scoring models (all thresholds extracted from source code), composite scoring mechanics, config tuning guide, cache/performance, advanced usage tips, and version history.
- **2026-03-17 v0.5.0**: Claude AI Re-Scoring Integration + post-review fixes (5 fixes). Opt-in qualitative AI layer that re-evaluates team scores using Claude API.
  - **New module `src/ai/`**: `client.py` (Anthropic SDK singleton with retry/graceful degradation), `prompts.py` (5 team-specific system prompts), `data_types.py` (`AIRescoreResult` dataclass).
  - **Score blending**: `blended = quant * (1 - ai_weight) + ai * ai_weight` (default 0.3). Applied post-team, pre-composite. One API call per active team, batching all tickers.
  - **CLI**: `--ai-rescore` flag enables AI re-scoring. YAML `ai_rescore.enabled` provides default, CLI overrides. API key via `ANTHROPIC_API_KEY` env var or `config/secrets.yaml`.
  - **Graceful degradation**: Missing SDK, missing API key, API errors, or parse failures all fall back to quant-only scores silently.
  - **Caching**: AI results cached with separate TTL (default 2h) to avoid repeated API calls. Cache key uses sorted tickers (order-independent).
  - **Config**: New `ai_rescore` section in `config/default.yaml` (enabled, model, temperature, ai_weight, batch_size, cache_ttl_hours, timeout_seconds, max_retries).
  - **Display**: AI scores shown in `print_summary()` with confidence level, reasoning excerpt, and flags.
  - **Dependencies**: `anthropic>=0.39.0` added as optional `[ai]` extra in `pyproject.toml`.
  - **Review fixes**: (1) `is_available()` duplicate warning suppression via `_availability_warned` flag, (2) `_call_api` RateLimitError now logs ERROR on final attempt before returning None, (3) score blending vectorized with `df.loc[]` replacing O(n) `iloc` loop, (4) `ai_rescore.enabled` config now actually read by orchestrator (CLI OR YAML), (5) removed dead `AIRescoreResult` import from orchestrator + fixed YAML comment header duplication.
- **2026-03-18 v1.0.0**: **10x Monster Stock Focus Overhaul** — Major architectural redesign to align the entire platform with its core mission: finding stocks that can 10x+.
  - **NEW: Purple Team** (`src/teams/purple/screener.py`): `TenBaggerScreener` evaluates structural 10x potential via 4 factors — `market_cap_tier` (piecewise breakpoints, nano=25 to large=0), `float_structure` (float size + insider ownership + low institutional), `dilution_risk` (inverted: cash/debt + OCF + share lockup), `explosive_setup` (BB squeeze + 52w position + OBV divergence + 5d return). Highest weight (1.3) in composite scoring.
  - **Global market cap gates**: Every team now filters out stocks exceeding configurable market cap ceilings — Red/Green/Blue/Purple: $2B, Yellow: $3B, Orange: $5B. Unknown market cap (`None`) passes through conservatively.
  - **Blue Team overhaul**: Replaced hardcoded large-cap list (AAPL, MSFT, GOOG, NVDA, META, AMZN removed) with dynamic Finviz small-cap momentum scan. New `get_small_cap_momentum_candidates()` in `finviz_scraper.py`. Analyst coverage bonus reduced (7→5pts), new 2pt "hidden gem" bonus for uncovered stocks. `min_momentum_score` lowered 60→40.
  - **Orange Team cleanup**: Removed TSLA/NVDA/AAPL from candidates. Market cap gate at $5B (gamma squeezes work on mid-caps).
  - **Red Team tightened**: `max_market_cap_millions` 10000→2000 in config.
  - **Orchestrator v2**: Resonance detection — when 3+ teams flag the same ticker, ×1.25 composite score multiplier. `🔥共振` tag in `print_summary()`. Rebalanced weights: `red×1.2, orange×1.0, yellow×0.7, green×1.2, blue×0.5, purple×1.3`.
  - **Config**: New `purple_team` section, `orchestrator.resonance_min_teams`, `orchestrator.resonance_multiplier`, `orchestrator.global_max_market_cap_millions`. Market cap thresholds added to orange/yellow/green/blue team configs. Green `max_price` 50→30.
  - **Global gate wired**: `orchestrator.global_max_market_cap_millions` ($5B) now enforced in `_merge_and_score()` as post-merge safety net — coalesces `meta_market_cap_millions` columns across teams, filters exceeding tickers.
  - **Files changed**: 10 files (2 new, 8 modified). `src/teams/purple/__init__.py`, `src/teams/purple/screener.py`, `src/pipeline/orchestrator.py`, `src/teams/blue/screener.py`, `src/teams/orange/screener.py`, `src/teams/green/screener.py`, `src/teams/yellow/screener.py`, `src/utils/finviz_scraper.py`, `config/default.yaml`, `CLAUDE.md`.
- **2026-03-18 v1.0.1**: Elite team audit — 12 issues fixed (3 P0, 3 P1, 6 P2) across 9 files.
  - **P0**: `main.py` — Purple team blocked from CLI (missing argparse choice), stale version "0.5.0"→"1.0.0", stale "Five-Team"→"Six-Team" description.
  - **P1**: Red team missing `market_cap_millions` in metadata (broke global market cap gate for Red-only tickers), Yellow fallback list had TSLA/NVDA (wasted API calls before $3B gate), `cache.py` redundant `mkdir` syscalls on every cache op (now lazy singleton).
  - **P2**: Red inlined `shortPercentOfFloat` extraction (eliminated redundant cache read), Purple `market_cap_millions` moved from signals→metadata, Green `_build_snapshot_from_hist` accepts pre-fetched `info`, `technical.py` dead variable removed, `base.py` docstring "five"→"six", `cache.py` simplified redundant exception hierarchy.
- **2026-03-18 v1.0.2**: Finviz alphabetical sampling bias fix — root cause of "same stocks every run".
  - **Root cause**: Finviz free tier ignores `o=` sort parameter, always returning results in alphabetical order. With `max_pages=3` (60 results), only A-C tickers ever appeared.
  - **Fix**: `screen()` now accepts `view` parameter (different views expose different columns). Each convenience function selects the Finviz view containing its sort column, then applies **client-side sorting** via new `sort_dataframe()` utility. `max_pages` increased 5→10 (200 results, ~15s first fetch, cached 1 hour).
  - **Per-team view & sort**: Red→VIEW_OWNERSHIP (sort by "Short Float" desc), Green/Blue→VIEW_PERFORMANCE (sort by "Rel Volume" desc), Purple→VIEW_OVERVIEW (sort by "Market Cap" asc).
  - **New API**: `VIEW_OVERVIEW`, `VIEW_OWNERSHIP`, `VIEW_PERFORMANCE`, `VIEW_FINANCIAL`, `VIEW_CUSTOM` constants. `sort_dataframe(df, column, ascending)` public utility.
  - **Finviz result caching**: 1-hour TTL, cache key includes view + order_by + max_pages for correctness.
  - **Files changed**: `src/utils/finviz_scraper.py`, `src/teams/purple/screener.py`.
