# SAnalysis - Change Log

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
