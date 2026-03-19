# SDE-Team Memory

## Project: SAnalysis (Meme Stock Analysis Platform)
- Root: `/home/kuzu/Repos/SAnalysis`
- Python 3.12, venv at `.venv/`
- **v1.0.0** (2026-03-18): 10x Monster Stock Focus Overhaul
- Git on `main` branch

## Architecture
- Layered: `src/core/` -> `src/utils/` -> `src/teams/{red,orange,yellow,green,blue,purple}/` -> `src/pipeline/` -> `main.py`
- AI module: `src/ai/` (Claude API re-scoring, opt-in via `--ai-rescore`)
- Config: `config/default.yaml` (YAML-driven, all thresholds configurable)
- Cache: File-based parquet/JSON in `data/cache/`, atomic writes via `_atomic_write()`, configurable TTL
- Data interface: All teams produce `ScreenResult` dataclass, orchestrator merges into DataFrame
- Base class: `BaseScreener` with `fetch_candidates()` + `analyze(ticker)` contract
- Exceptions: `src/core/exceptions.py` (SAnalysisError hierarchy; TickerValidationError inherits both SAnalysisError and ValueError; AIRescoreError)
- Lazy loading: Orchestrator uses dynamic import registry (`_SCREENER_REGISTRY` module-level), only instantiates requested teams

## Key Files
- Entry: `main.py` (CLI with --teams, --tickers, --top, --no-parallel, --version, --clear-cache, --no-save, --ai-rescore)
- Config: `src/core/config.py` (thread-safe singleton, YAML + env var merge, `get_nested()` for safe deep access)
- Cache: `src/core/cache.py` (atomic writes with fd_closed flag, DRY _atomic_write, clear_cache())
- Types: `src/core/data_types.py` (ScreenResult with `dict[str, Any]` metadata, timezone-aware timestamps)
- Exceptions: `src/core/exceptions.py` (SAnalysisError -> ConfigError, DataFetchError, CacheError, ScreenerError, TickerValidationError, AIRescoreError)
- Base: `src/core/base.py` (validate_ticker raises TickerValidationError, timing, dedup)
- Market data: `src/utils/market_data.py` (yfinance wrapper with ticker object reuse)
- Technical: `src/utils/technical.py` (pandas_ta with manual fallbacks, vectorized S/R)
- Finviz: `src/utils/finviz_scraper.py` (HTML parser for free tier + convenience functions)
- Pipeline: `src/pipeline/orchestrator.py` (lazy loading, per-team timing, resonance detection, global market cap gate, AI re-scoring)
- AI: `src/ai/client.py` (Anthropic SDK singleton), `src/ai/prompts.py` (5 team prompts), `src/ai/data_types.py` (AIRescoreResult)

## Scoring
- Each team: 4 factors × 25 points = 100 max per team
- Composite: weighted average across teams: `red×1.2, orange×1.0, yellow×0.7, green×1.2, blue×0.5, purple×1.3`
- Resonance bonus: 3+ teams flagging same ticker → ×1.25 composite multiplier
- AI re-scoring (opt-in): `blended = quant×(1-0.3) + ai×0.3`
- Global market cap gate: post-merge filter at $5B (`orchestrator.global_max_market_cap_millions`)

## Market Cap Gates (v1.0.0)
| Team | Threshold | Config Key |
|------|-----------|-----------|
| Red | $2B | `red_team.max_market_cap_millions` |
| Orange | $5B | `orange_team.max_market_cap_millions` |
| Yellow | $3B | `yellow_team.max_market_cap_millions` |
| Green | $2B | `green_team.max_market_cap_millions` |
| Blue | $2B | `blue_team.max_market_cap_millions` |
| Purple | $2B | `purple_team.max_market_cap_millions` |
| Global | $5B | `orchestrator.global_max_market_cap_millions` |

## Team ↔ Code ↔ Agent Mapping
| Color | Python Class | File | Config Key | Agent |
|-------|-------------|------|-----------|-------|
| red | ShortSqueezeScreener | src/teams/red/screener.py | red_team | short-squeeze-sniper |
| orange | GammaSqueezeScreener | src/teams/orange/screener.py | orange_team | gamma-flow-hunter |
| yellow | SocialSentimentScreener | src/teams/yellow/screener.py | yellow_team | social-sentiment-quant |
| green | LowFloatBreakoutScreener | src/teams/green/screener.py | green_team | low-float-breakout |
| blue | MomentumCatalystScreener | src/teams/blue/screener.py | blue_team | momentum-catalyst-fusion |
| purple | TenBaggerScreener | src/teams/purple/screener.py | purple_team | (none yet) |

## v1.0.0 Key Architecture Decisions
- **Purple Team**: Highest composite weight (1.3) — structural 10x potential is the most important signal
- **Blue Team downweighted (0.5)**: Momentum alone is noisy for small caps; combined with other signals via resonance
- **Resonance detection**: Multi-signal convergence (3+ teams) is the strongest predictor of explosive moves
- **Per-team gates + global gate**: Defense in depth — individual teams filter first, orchestrator applies final safety net
- **Unknown mcap passes through**: Conservative approach — don't filter what we can't verify
- **meta_ prefix**: ScreenResult metadata serialized with `meta_` prefix in DataFrames; signals with `sig_` prefix then renamed to `{team}_{signal_name}`

## Dependencies
- yfinance, pandas, numpy, pandas_ta, pyyaml, requests, beautifulsoup4, lxml
- vaderSentiment, pytrends, plotly, matplotlib, pyarrow
- Optional: praw (needs Reddit API keys, [reddit] extra), anthropic (AI re-scoring, [ai] extra)

## Remaining Known Issues (P2, not yet fixed)
- Red: scoring thresholds still hardcoded (not from config), _collect_short_data double-calls get_ticker_info, no ADR data confidence flagging
- Orange: only single expiry analyzed, no IV Rank/Percentile, 0DTE Vol/OI handling, _oi_concentration_proxy still basic
- Yellow: ticker regex false positives (e.g., "CEO" variants), bot filter config (min_account_age, min_karma) unused, per-namespace cache TTL
- Green: no reverse split detection, no dynamic consolidation thresholds, MACD not in docstring metadata output
- Blue: ADX/relative strength not used, Jegadeesh-Titman skip-recent-month not implemented, market_regime doesn't differentiate individual stocks
- Purple: no purple-specific analysis agent defined yet

## Environment Notes
- Ubuntu 24.04 on WSL2, Python 3.12.3
- Must use venv (externally-managed-environment restriction)
- Activate: `source /home/kuzu/Repos/SAnalysis/.venv/bin/activate`
