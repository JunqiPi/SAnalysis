# SAnalysis - Change Log

## [1.0.0] - 2026-03-18

### 10x Monster Stock Focus Overhaul

**Implemented by**: SDE-Team (2 new files, 8 modified files)

**Motivation**: The platform's core mission is finding stocks that can achieve 10x+ returns. However, large-cap stocks (AAPL $3.5T, MSFT $3.2T, GOOG, NVDA, META, AMZN) were polluting candidates across multiple teams. These mega-caps cannot 10x in any reasonable timeframe. This release implements a comprehensive architectural redesign: a new Purple Team for structural 10x potential assessment, global market cap gates across all teams, dynamic small-cap candidate sourcing, orchestrator resonance detection, and rebalanced composite weights.

#### New Team: Purple — 10x Potential Assessor (`src/teams/purple/`)

- **`src/teams/purple/__init__.py`**: Package init exposing `TenBaggerScreener`.
- **`src/teams/purple/screener.py`**: `TenBaggerScreener(BaseScreener)` — evaluates structural characteristics for 10x+ return potential.
- **Candidate discovery**: Primary source is Finviz `screen()` with `cap_smallunder` + `sh_avgvol_o200` + `sh_price_o1`. Fallback: 21-ticker curated list of historically volatile micro/small-cap stocks (FFIE, MULN, SOFI, MARA, RIOT, etc.).
- **Scoring model (4 × 25 = 100)**:
  - `market_cap_tier` (0-25): Piecewise breakpoints from nano cap ($<50M, 25pts) to large cap ($≥5B, 0pts). Hard gate at configurable `max_market_cap_millions` (default $2B).
  - `float_structure` (0-25): Float size (0-10, smaller=better), insider ownership (0-8, higher=better alignment), institutional ownership (0-7, lower=better for squeeze potential).
  - `dilution_risk` (0-25, inverted): Cash/debt ratio (0-10), OCF/FCF sustainability (0-8, positive OCF=self-funding=no dilution pressure), share structure float/outstanding ratio (0-7).
  - `explosive_setup` (0-25): BB width compression vs 20-day average (0-8), 52-week range position (0-6, sweet spot 10-30% from low), OBV divergence/accumulation (0-6), 5-day return momentum (0-5).
- **Design**: Defensive config access (`self.cfg.data.get("purple_team", {})`), sub-score decomposition into 4 `@staticmethod` methods, OCF-based cash runway heuristic.

#### Global Market Cap Gates (All 6 Teams)

Every team now filters stocks exceeding configurable market cap ceilings in their `analyze()` method:

| Team | Threshold | Rationale |
|------|-----------|-----------|
| Red | $2B (was $10B) | Short squeezes most explosive in small caps |
| Orange | $5B (new) | Gamma squeezes work on mid-caps with liquid options |
| Yellow | $3B (new) | Social sentiment actionable for small/mid caps |
| Green | $2B (new) | Low-float breakouts require small caps |
| Blue | $2B (new) | Momentum-driven 10x potential only in small caps |
| Purple | $2B (new) | Structural 10x potential requires small market cap |

- **Orchestrator global gate**: Post-merge `global_max_market_cap_millions` ($5B) filters any tickers that slipped through individual team gates. Coalesces `meta_market_cap_millions` across all teams.
- All gates use pattern: `if mcap is not None and mcap > max_mcap * 1e6`. Unknown market cap (`None`) passes through conservatively.
- All filtering uses `logger.debug` to avoid log noise from expected filtration.

#### Blue Team 10x Overhaul (`src/teams/blue/screener.py`)

- **Dynamic candidate sourcing**: Replaced hardcoded 27-ticker list (included 8 large-caps) with `finviz_scraper.get_small_cap_momentum_candidates()` querying Finviz for <$2B market cap stocks with RVOL >1.5x. Falls back to curated 18-ticker small/micro-cap list (`_fallback_tickers()`).
- **New function**: `get_small_cap_momentum_candidates()` in `src/utils/finviz_scraper.py` — maps friendly names to Finviz filter codes, follows same pattern as existing convenience functions.
- **Scoring adjustment**: Analyst coverage bonus reduced 7→5pts. New 2pt "hidden gem" bonus for uncovered stocks (under-the-radar = higher 10x potential). Max score: analyst=23/25, no analyst=20/25.
- **Config**: `min_momentum_score` lowered 60→40 (small caps have choppier momentum signals).

#### Orange Team Cleanup (`src/teams/orange/screener.py`)

- **Candidates**: Removed TSLA, NVDA, AAPL. Added GOEV. List reorganized into thematic groups.
- **Market cap gate**: $5B threshold after spot price check.

#### Orchestrator v2 (`src/pipeline/orchestrator.py`)

- **Purple Team integration**: Added to `_SCREENER_REGISTRY`, `TEAM_DISPLAY` (🟣十倍潜力评估师), and `TEAM_ORDER`.
- **Resonance detection**: When `resonance_min_teams` (default 3) or more teams flag the same ticker with score > 0, a `resonance_multiplier` (default ×1.25) is applied to the composite score. `🔥共振` tag in `print_summary()`.
- **Rebalanced weights**: `red×1.2, orange×1.0, yellow×0.7, green×1.2, blue×0.5, purple×1.3` — 10x-aligned teams (red, green, purple) upweighted, noisier signals (yellow, blue) downweighted.
- **Global market cap gate**: Post-merge filter using `orchestrator.global_max_market_cap_millions` ($5B) as final safety net.

#### Config Changes (`config/default.yaml`)

- `red_team.max_market_cap_millions`: 10000 → 2000
- `orange_team.max_market_cap_millions`: 5000 (new)
- `yellow_team.max_market_cap_millions`: 3000 (new)
- `green_team.max_price`: 50.0 → 30.0
- `green_team.max_market_cap_millions`: 2000 (new)
- `blue_team.min_momentum_score`: 60 → 40
- `blue_team.max_market_cap_millions`: 2000 (new)
- New `purple_team` section: `max_market_cap_millions`, `ideal_market_cap_millions`, `max_float_millions`, `min_insider_pct`
- `orchestrator.team_weights`: rebalanced for 6 teams
- `orchestrator.global_max_market_cap_millions`: 5000 (new)
- `orchestrator.resonance_min_teams`: 3 (new)
- `orchestrator.resonance_multiplier`: 1.25 (new)

---

## [0.5.0] - 2026-03-17

### Claude AI Re-Scoring Integration + Post-Review Fixes

**Implemented by**: SDE-Team (new feature + 5 review fixes)

#### New Feature: AI Re-Scoring Module (`src/ai/`)
- **`src/ai/client.py`**: Thread-safe singleton Anthropic SDK wrapper with double-checked locking, retry with exponential backoff, and graceful degradation (missing SDK, missing key, auth failure, rate limit, API errors all fall back to quant-only).
- **`src/ai/prompts.py`**: 5 team-specific system prompts (red=squeeze analyst, orange=options microstructure, yellow=sentiment forensics, green=breakout specialist, blue=momentum/catalyst timing). JSON-only response format with valid flag enumerations.
- **`src/ai/data_types.py`**: `AIRescoreResult` dataclass (ai_score, ai_confidence, ai_reasoning, ai_flags, blended_score).
- **Score blending**: `blended = quant * (1 - ai_weight) + ai * ai_weight` (default ai_weight=0.3). Applied per-team post-scoring, pre-composite merge.
- **Caching**: AI results cached via existing `cache_json`/`load_cached_json` with separate TTL (default 2h). Cache key uses sorted tickers to avoid order-dependent misses.
- **CLI**: `--ai-rescore` flag. API key via `ANTHROPIC_API_KEY` env var or `config/secrets.yaml`.
- **Config**: New `ai_rescore` section in `config/default.yaml` (enabled, model, max_tokens, temperature, ai_weight, batch_size, cache_ttl_hours, timeout_seconds, max_retries).
- **Display**: `print_summary()` shows AI score, confidence, reasoning excerpt (truncated to 120 chars), and flags per team per ticker.
- **Dependencies**: `anthropic>=0.39.0` as optional `[ai]` extra in `pyproject.toml`, included in `[all]`.
- **Exception**: `AIRescoreError` added to `src/core/exceptions.py` hierarchy.

#### Review Fix 1: `is_available()` Duplicate Warning Suppression
- **Bug**: `is_available()` logged a WARNING on every call. Since it's called both in `PipelineOrchestrator.__init__()` (via `AIClient.instance().is_available()`) and in `rescore_batch()` (defensive check per team), the same warning was emitted 5+ times per run when the SDK or key was missing.
- **Fix**: Added `_availability_warned` flag to `AIClient.__init__()`. Each warning branch now checks and sets this flag, logging only on the first invocation.

#### Review Fix 2: `_call_api` RateLimitError Silent Exhaustion
- **Bug**: The `RateLimitError` except block slept and retried but had no terminal error log. After exhausting all retries, the loop fell through to the bare `return None` at the bottom, producing no ERROR log (only WARNINGs per attempt). The `APIStatusError`/`APIConnectionError` block correctly logged an ERROR on the final attempt.
- **Fix**: Added `if attempt >= max_retries: logger.error(...)` + `return None` at the top of the `RateLimitError` handler, matching the pattern used by the other API error handler.

#### Review Fix 3: `_apply_ai_rescoring` Score Blending Vectorized
- **Bug**: Score blending used a row-by-row `for i in range(len(df))` loop with `df.iloc[i, df.columns.get_loc(score_col)]` assignment. While technically correct for avoiding `SettingWithCopyWarning` (the df is the original, not a slice), this is O(n) with high per-iteration overhead from `iloc` + `get_loc` inside the loop. Also a pandas anti-pattern.
- **Fix**: Replaced with vectorized `df.loc[has_ai, score_col] = ...` using a boolean mask `has_ai = pd.notna(df[ai_score_col])`. Single pandas operation, no loop.

#### Review Fix 4: `ai_rescore.enabled` Config Field Dead Code
- **Bug**: `config/default.yaml` defined `ai_rescore.enabled: false` with comment "Master switch (CLI --ai-rescore overrides)", but no code read this field. The only activation path was the `--ai-rescore` CLI flag. Users setting `enabled: true` in config would see no effect.
- **Fix**: `PipelineOrchestrator.__init__()` now resolves AI enablement as `ai_rescore OR config.ai_rescore.enabled`. CLI flag remains the override; YAML provides the default.

#### Review Fix 5: Unused Import + YAML Comment Header Cleanup
- **Dead import**: Removed unused `from src.ai.data_types import AIRescoreResult` in `_apply_ai_rescoring()` (the method works with raw dicts, not the dataclass).
- **YAML formatting**: Fixed duplicate comment header in `config/default.yaml` where the Orchestrator section header was merged with the AI Re-Scoring section header. Each section now has its own clean comment block.

---

## [0.4.1] - 2026-03-17

### Infrastructure Hardening & Scoring Bugfix

**Implemented by**: SDE-Team (5 targeted fixes)

#### Fix 1: Configurable Network Timeouts
- **New config key**: `general.network_timeout_seconds` (default 30s) in `config/default.yaml`.
- **Finviz scraper**: `requests.get()` in `screen()` now reads timeout from config via `get_config().get_nested()` instead of hardcoded `timeout=15`. Falls back to module-level `_DEFAULT_TIMEOUT_SECONDS = 30` if config key is missing.
- **yfinance limitation documented**: `market_data.py` module docstring now explains that yfinance manages its own internal `requests.Session` and does not expose a timeout parameter. The config key applies only to direct `requests` calls.

#### Fix 2: Blue Team Negative D/E Scoring Bug
- **Bug**: In `_score_financial_quality`, the D/E scoring chain started with `if de < 0.5: score += 5.0`. A negative D/E (e.g., -2.0) -- indicating negative shareholder equity / insolvency -- passed this condition, scoring 5 points as "very low debt".
- **Fix**: Added explicit `if de < 0: pass` guard before the positive-value scoring chain. Insolvent companies now receive 0 additional D/E points instead of 5.

#### Fix 3: Orchestrator Team Weights Moved to Config
- **New config section**: `orchestrator.team_weights` in `config/default.yaml` with the same values previously hardcoded in `orchestrator.py` (`red: 1.0, orange: 1.0, yellow: 0.8, green: 1.0, blue: 0.9`).
- **Code change**: `PipelineOrchestrator.__init__()` now reads weights with 3-tier priority: explicit `team_weights` constructor arg > `orchestrator.team_weights` from config YAML > `_FALLBACK_TEAM_WEIGHTS` hardcoded constant.
- **Backward compatible**: Renamed module constant from `DEFAULT_TEAM_WEIGHTS` to `_FALLBACK_TEAM_WEIGHTS` (private). Callers passing explicit `team_weights=` are unaffected.

#### Fix 4: YAML Parsing Error Handling in Config
- **Bug**: `yaml.safe_load()` calls in `Config._load()` were not wrapped in try/except. A malformed YAML file would raise an opaque `yaml.YAMLError` with no indication of which file failed.
- **Fix**: Both `default.yaml` and `secrets.yaml` parsing are now wrapped in `try/except yaml.YAMLError`. On failure: logs an ERROR with the exact file path and error details, then raises `ConfigError` (from `src/core/exceptions.py`) with a descriptive message, chaining the original exception via `from exc`.
- **New import**: `config.py` now imports `ConfigError` from `src.core.exceptions`.

#### Fix 5: Yellow Team `_score_momentum` TypeError on None Mentions
- **Bug**: In `_score_momentum`, `aw_data.get("mentions_24h_ago", 0)` used a default of `0`, but when the key exists with an explicit `None` value, `dict.get()` returns `None` (the default only applies for missing keys). The subsequent comparison `None > 0` at line 584 raised `TypeError: '>' not supported between instances of 'NoneType' and 'int'`. The same latent issue affected `"mentions"` and the `current > 0` branch.
- **Fix**: Changed both lines to use `or 0` coalescion: `aw_data.get("mentions") or 0` and `aw_data.get("mentions_24h_ago") or 0`. This handles both missing-key and explicit-`None` cases, coalescing to `0` in either scenario.

---

## [0.4.0] - 2026-02-24

### P1 Scoring Refinement & Robustness Improvements

**Implemented by**: SDE-Team (15 P1 fixes across all 5 teams + core infrastructure)

#### Red Team — Config Enforcement, Scoring Smoothing, Data Freshness
- **ShortData.as_of population**: Now extracts `dateShortInterest` from yfinance `info` dict, converting Unix timestamp to timezone-aware datetime. Enables staleness tracking.
- **Short data staleness warning**: Logs WARNING when SI data is >16 days old (FINRA publishes every ~15 days).
- **Config-driven gates enforced**: `min_days_to_cover` and `max_market_cap_millions` from `config/default.yaml` are now checked in `analyze()`. Previously defined but never used — stocks with DTC<3 or market cap >$10B are now correctly filtered.
- **Scoring step discontinuity fix**: Replaced step-function scoring in `_score_short_intensity` with piecewise linear interpolation. Eliminates the 2-point cliff between 9.9% and 10.0% SI.
- **NaN signals for missing data**: `days_to_cover` and `put_call_ratio` now emit `float("nan")` instead of `0` when data is unavailable, allowing downstream consumers to distinguish "not available" from "is zero".
- **Finviz empty result logging**: Logs warning when Finviz returns empty results (possible rate limit) instead of silently falling back.
- **Catalyst exception logging**: Earnings date parsing failures now logged at DEBUG level with traceback instead of bare `except: pass`.

#### Blue Team — Meme-Stock Financial Quality, VIX Safety Valve
- **Financial quality baseline**: Every stock starts with 5/25 baseline score. Meme stocks with poor financials now get 6-12/25 instead of 0/25. Slight revenue decline (-20% to 0%) gets 1pt instead of 0. This is a momentum screener, not a value screener.
- **VIX regime multiplier**: `analyze()` now applies a global discount factor when VIX is elevated: VIX≥35 → 0.5x total score, VIX≥25 → 0.7x total score. This is the "safety valve" — it proportionally suppresses ALL factor scores in high-vol regimes, not just the market_regime factor.
- **regime_multiplier in metadata**: Output now includes `regime_multiplier` for transparency.
- **Earnings exception traceback**: DEBUG logging now includes `exc_info=True`.

#### Green Team — MACD Integration, RVOL Price Direction Verification
- **MACD in _score_technical_setup**: Docstring claimed "RSI, MA, BB, MACD" but code only had RSI, MA, BB. Now computes MACD from history and scores fresh bullish crossovers (within 3 days) at 4pts, ongoing bullish at 2pts.
- **RVOL price direction check**: `_score_volume_explosion` now verifies that high RVOL accompanies a price *increase*. High RVOL on a >3% decline is discounted by 70% (distribution, not accumulation). Mild decline discounted by 40%.
- **Scoring rebalance**: Sub-factor point allocations adjusted (RSI 7→6, MA 7→6, BB 6→5, VWAP 5→4) to accommodate MACD (0→4) within the 25pt ceiling.
- **Signature change**: `_score_technical_setup` and `_score_volume_explosion` now take `hist` parameter.

#### Yellow Team — Google Trends Circuit Breaker, Reddit Client Caching
- **Google Trends circuit breaker**: After 3 consecutive failures, the GT circuit breaker opens and all subsequent calls return None immediately. Prevents cascade timeouts when Google rate-limits the scan. Resets on any successful cache hit or API response.
- **Reddit client caching**: `praw.Reddit()` is now created once per scan run (lazy-init in `_get_reddit_client()`) and reused across all ticker analyses. Previously recreated the OAuth session for every ticker in `_get_reddit_sentiment()` and `_scan_reddit_for_tickers()`.
- **Centralized Reddit client**: Both `_scan_reddit_for_tickers` and `_get_reddit_sentiment` now use `_get_reddit_client()`.

#### Orange Team — OI-Weighted PCR, GEX Magnitude Normalization
- **OI-weighted put/call ratio**: Added `put_call_ratio_oi` to `OptionsSnapshot` dataclass. Computed alongside volume-based PCR. OI-weighted PCR is more stable (less intraday noise) and now used in `_score_oi_setup`.
- **GEX magnitude normalization**: `_score_gex` no longer uses binary sign (positive=12, negative=2). Now computes GEX imbalance ratio (`|net_gex| / total_gex`) and scores on a 3-tier scale: extreme (≥0.7 → 14pts), strong (≥0.4 → 11pts), mild (8pts). A tiny positive GEX is no longer scored the same as a massive one.
- **GEX flip distance scoring**: Flip point proximity to spot now matters — within 5% of spot gets 4pts (high transition risk), further away gets 2pts.
- **OI setup rebalance**: Sub-factor allocations adjusted for the new OI-weighted PCR (absolute OI 8→7, call dominance 7→6, new PCR_OI 0→5, vol/OI 5→4).

#### Core Infrastructure
- **OptionsSnapshot.put_call_ratio_oi**: New field in `src/core/data_types.py` for OI-weighted P/C ratio.

---

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
