# SAnalysis - Change Log

## [0.3.0] - 2026-02-24

### Scoring Logic & Data Integrity Overhaul (P0 Fixes)

**Implemented by**: SDE-Team (5-team specialist agent audit → 20 P0 issues identified and fixed)

#### CRITICAL: Orange Team — GEX Sign Convention Fix
- **INVERTED GEX scoring** (most severe bug): `_score_gex` was giving 12pts for negative net_gex, but positive net_gex (call_gex > put_gex) means dealers are short gamma = amplifies moves = squeeze-prone. **Fix**: swapped sign convention; positive net_gex now correctly scores highest.
- **GEX flip point**: `_find_gex_flip` was using per-strike sign changes instead of cumulative GEX. Fixed to use `cumsum()` — flip point is now where cumulative net GEX crosses zero.
- **OTM call definition**: `_detect_unusual_activity` was using `calls["strike"].median()` for OTM threshold. Fixed to use actual `spot` price (fundamental definition of OTM).
- **Vectorized GEX calculation**: Replaced 4x `iterrows()` loops with pandas vectorized operations in `_estimate_gex` and `_find_gex_flip`. ~10x speedup for large option chains.

#### Blue Team — Momentum Scoring Fixes
- **Momentum normalization bias**: `(ret + 50) * (100/150)` mapped 0% return to 33.3 instead of 50 (neutral). Fixed to symmetric `max(0, min(100, ret + 50))` where 0% = 50.
- **Revenue growth double-counting**: `revenue_growth_pct` was scored in both `_score_catalyst` (0-5pts) and `_score_financial_quality` (0-10pts). Removed from `_score_catalyst`.
- **Config: lookback_months 6→14**: `momentum_periods` includes 252 trading days (~12 months), but `lookback_months=6` only fetched 126 days. Fixed to 14 months.
- **min_momentum_score enforcement**: Config defined `min_momentum_score=60` but `analyze()` never checked it. Now implemented as gate in `analyze()`.
- **Earnings date sort safety**: `future[0]` assumed ascending sort from yfinance. Added explicit `.sort_values()`.

#### Red Team — Data Integrity Fixes
- **Stale fallback tickers**: Removed BBBY (delisted 2023), RIDE (bankrupt), SKLZ, WISH. Added SOFI, MARA, RIOT.
- **SI% validation**: Added cap at 100% for implausible short interest data (common with ADRs like ABX showing 43% SI).
- **Put/call ratio minimum volume**: Added `_MIN_PCR_VOLUME = 100` threshold. Low-volume P/C ratios are statistically unreliable.
- **API call deduplication**: `_score_catalyst` and `_score_technical` now receive pre-fetched `hist` DataFrame from `analyze()`.
- **Earnings sort safety**: Added `.sort_values()` for future earnings dates.

#### Green Team — Performance & Filter Fixes
- **3x API call elimination**: `analyze()` now fetches 6mo history once and passes it to `_build_snapshot_from_hist()`, `_score_breakout_quality()`, and slices for support/resistance. Eliminates 2 redundant yfinance calls per ticker.
- **OBV duplication removed**: `_score_breakout_quality` no longer recalculates OBV (already computed in `_build_snapshot`).
- **SPAC filter expansion**: `_EXCLUDED_INDUSTRIES` expanded from 2 to 7 entries (added closed-end funds, ETFs, SPACs).
- **Float unknown default**: Reduced from 5.0 → 2.0 (no evidence of float tightness should not grant a moderate score).

#### Yellow Team — Data Caching & Scoring Fixes
- **ApeWisdom data caching**: `_fetch_apewisdom()` now caches the FULL response (mentions, rank, upvotes, mentions_24h_ago) in a single API call. `_get_apewisdom_ticker()` no longer re-fetches the same URL per ticker.
- **VADER financial lexicon overlay**: Added 20+ financial term corrections (e.g., "short"→neutral, "squeeze"→bullish, "moon"→strongly bullish, "retard"→neutral in WSB context).
- **Momentum double-counting fix**: `_score_momentum` and `_score_mention_frequency` were both using Google Trends score + ApeWisdom rank. Now separated: `mention_frequency` = absolute attention level (mentions + rank), `momentum` = acceleration (GT score + mention change rate via `mentions_24h_ago`).
- **Quality scoring rebalanced**: Single-source (ApeWisdom only) configuration now gets 4pts instead of 3pts for source diversity, since Reddit penalty is already applied in `sentiment_polarity`.

#### Core Infrastructure Fixes
- **cache.py double-close bug**: `_atomic_write` error handler could close an already-closed fd. Fixed with `fd_closed` flag.
- **cache_dataframe DRY**: Eliminated duplicate temp-file-then-rename logic; now uses `_atomic_write()` with `df.to_parquet()` bytes output.
- **TickerValidationError**: `validate_ticker()` now raises `TickerValidationError` instead of bare `ValueError`. `TickerValidationError` inherits from both `SAnalysisError` and `ValueError` for backward compatibility.
- **Type hints**: `ScreenResult.metadata` type hint changed from bare `dict` to `dict[str, Any]`.
- **Unused import**: Removed `from datetime import datetime` in `market_data.py`.

---

## [0.2.0] - 2026-02-24

### Codebase Maturity Overhaul

**Implemented by**: SDE-Team (full-team deep review + 5 specialist agent audits)

#### Core Infrastructure Hardening (src/core/)
- **Thread-safe Config singleton**: Added `threading.Lock` with double-checked locking pattern to `Config.get()` / `Config.reload()`. Prevents race conditions when ThreadPoolExecutor workers access config simultaneously.
- **Atomic cache writes**: `cache.py` now writes to temp files then atomically renames via `os.replace()`. Eliminates partial-read corruption when parallel threads write to the same cache key.
- **Cache management**: Added `clear_cache(namespace)` function for selective or full cache purge.
- **Timezone-aware timestamps**: Replaced all `datetime.utcnow()` (deprecated in Python 3.12) with `datetime.now(timezone.utc)` via `_utcnow()` helper across all dataclasses.
- **ScreenResult metadata preservation**: `to_dict()` now includes scalar metadata fields (prefixed `meta_`) alongside signal fields, preventing data loss during DataFrame serialization.
- **Custom exception hierarchy**: New `src/core/exceptions.py` with `SAnalysisError` base and specific subtypes (`ConfigError`, `DataFetchError`, `CacheError`, `ScreenerError`, `TickerValidationError`).
- **Ticker input validation**: `validate_ticker()` in `base.py` normalizes (strip + uppercase) and validates against regex pattern. Rejects empty strings, special characters, and tickers >5 chars.
- **BaseScreener improvements**: Automatic ticker deduplication, per-run timing metrics, validated tickers, and enhanced logging with elapsed time and pass/fail counts.

#### Pipeline & Performance (src/pipeline/, src/utils/)
- **Lazy screener loading**: Orchestrator now uses a registry + dynamic import pattern. Only requested teams are instantiated, reducing startup time when running `--teams red` from ~3s to ~0.5s.
- **Per-team timing**: Each team's `run()` and orchestrator wrapper now log wall-clock execution time.
- **yfinance Ticker object reuse**: `market_data.py` now caches `yf.Ticker` objects (thread-safe) instead of creating new instances per call. Reduces redundant Yahoo Finance session initialization.
- **Vectorized support/resistance**: `compute_support_resistance()` rewritten from O(n*window) Python loops to O(n) pandas rolling operations.
- **relative_volume edge case**: Fixed silent empty-slice bug when data length < lookback+1.

#### Bug Fixes (from v0.1.2, now included)
- Fixed `detect_breakout()` direction blindness: now requires `price_change > 0` (was using `abs()` which caught -40% crashes as "breakouts").
- Added SPAC/shell company exclusion filter in green team (`_EXCLUDED_INDUSTRIES` frozenset).
- Added Reddit API credential warning in yellow team (`_check_reddit_credentials()` logs WARNING once).

#### CLI & Configuration
- **`--version` flag**: `python main.py -V` now prints `SAnalysis v0.2.0`.
- **`--clear-cache` flag**: Purge all cached data before running a fresh scan.
- **`--no-save` flag**: Replaces confusing `--save` (was always true). Now opt-out instead of opt-in.
- **Improved secrets template**: `config/secrets.yaml.example` now includes setup instructions and env var mappings.
- **pyproject.toml**: Version bumped to 0.2.0, moved `praw` to optional `[reddit]` extra, added `pyarrow` as explicit dependency, added `pytest` config.
- **Red team import fix**: Moved `from datetime import datetime, timezone` from inside `_score_catalyst()` to module-level (was a code smell).

#### Project Infrastructure
- **Git initialization**: Repository initialized with comprehensive `.gitignore`.
- **Exception hierarchy**: Clean error taxonomy for all application-specific failures.
- **Module exports**: `src/core/__init__.py` now exports all public symbols including exceptions and validators.

---

## [0.1.2] - 2026-02-24

### Bug Fixes from First Production Run

- Fixed `detect_breakout()` in `src/utils/technical.py`: upside direction check.
- Added SPAC/shell company exclusion in `src/teams/green/screener.py`.
- Added Reddit API credential warning in `src/teams/yellow/screener.py`.

---

## [0.1.1] - 2026-02-23

### Agent Configuration Audit

- Created CLAUDE.md (shared project context for all agents)
- Aligned agent colors with Python team colors
- Added code awareness to all 5 analysis agents
- Fixed SDE-Team description and tools restrictions
- Added analysis agent tool restrictions (no Write/Edit)

---

## [0.1.0] - 2026-02-23

### Phase 1: Zero-Cost Prototype System

**Implemented by**: SDE-Team

#### Architecture
- Established layered architecture: Core -> Utils -> Teams -> Pipeline -> Main
- Unified DataFrame-based data interface across all five teams
- YAML-driven configuration system with secrets separation and env var overrides
- File-based caching (Parquet for DataFrames, JSON for dicts) with configurable TTL
- Abstract base screener class (`BaseScreener`) enforcing consistent team interface
- Canonical data types (`ScreenResult`, `ShortData`, `OptionsSnapshot`, `SentimentSnapshot`, `TechnicalSnapshot`, `MomentumSnapshot`)

#### Data Infrastructure (src/utils/)
- **market_data.py**: Centralized yfinance wrapper with caching for all teams
- **finviz_scraper.py**: Finviz free-tier HTML screener parser
- **technical.py**: Technical indicator library with pandas_ta backend + manual fallbacks

#### Five Team Screeners
- **Red Team**: Short squeeze screening (Finviz + yfinance short data + P/C ratio)
- **Orange Team**: Gamma squeeze detection (GEX estimation + unusual options + IV analysis)
- **Yellow Team**: Social sentiment quantification (ApeWisdom + Reddit + Google Trends + VADER)
- **Green Team**: Low float breakout detection (Finviz + full technical snapshot + breakout patterns)
- **Blue Team**: Momentum + catalyst fusion (multi-timeframe momentum + earnings + financials + VIX regime)

#### Pipeline & CLI
- Parallel multi-team execution via ThreadPoolExecutor
- Weighted composite scoring across teams
- CLI: `--teams`, `--tickers`, `--top`, `--no-parallel`, `--log-level`
- CSV watchlist export + human-readable console summary

### Data Sources (Phase 1, $0/month)
| Source | Purpose | Status |
|--------|---------|--------|
| yfinance | Prices, fundamentals, options, earnings | Active |
| Finviz (free) | Screener, short float, float, RVOL | Active |
| ApeWisdom | Reddit/4chan mention trending | Active |
| Google Trends | Search interest spikes | Active |
| VADER Sentiment | Text sentiment scoring | Active |
| praw (Reddit) | Direct subreddit scanning | Ready (needs API keys) |
| FINRA Short Interest | Official SI data | Planned (manual import) |
