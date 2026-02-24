# SDE-Team Memory

## Project: SAnalysis (Meme Stock Analysis Platform)
- Root: `/root/Pi/SAnalysis`
- Python 3.12, venv at `.venv/`
- Phase 1 complete (v0.1.0, 2026-02-23): Zero-cost prototype with 5 teams

## Architecture
- Layered: `src/core/` -> `src/utils/` -> `src/teams/{red,orange,yellow,green,blue}/` -> `src/pipeline/` -> `main.py`
- Config: `config/default.yaml` (YAML-driven, all thresholds configurable)
- Cache: File-based parquet/JSON in `data/cache/`, configurable TTL
- Data interface: All teams produce `ScreenResult` dataclass, orchestrator merges into DataFrame
- Base class: `BaseScreener` with `fetch_candidates()` + `analyze(ticker)` contract

## Key Files
- Entry: `main.py` (CLI with --teams, --tickers, --top, --no-parallel)
- Config: `src/core/config.py` (singleton, YAML + env var merge)
- Cache: `src/core/cache.py` (parquet for DF, JSON for dicts)
- Types: `src/core/data_types.py` (ScreenResult, ShortData, OptionsSnapshot, etc.)
- Market data: `src/utils/market_data.py` (centralized yfinance wrapper with cache)
- Technical: `src/utils/technical.py` (pandas_ta with manual fallbacks)
- Finviz: `src/utils/finviz_scraper.py` (HTML parser for free tier)
- Pipeline: `src/pipeline/orchestrator.py` (parallel execution, weighted composite score)

## Scoring
- Each team: 4 factors x 25 points = 100 max per team
- Composite: weighted average across teams (yellow weighted 0.8, blue 0.9, others 1.0)

## Dependencies
- yfinance, pandas, numpy, pandas_ta, pyyaml, requests, beautifulsoup4, lxml
- vaderSentiment, pytrends, plotly, matplotlib, pyarrow
- Optional: praw (needs Reddit API keys)

## Team ↔ Code ↔ Agent Mapping
| Color | Python Class | File | Config Key | Agent |
|-------|-------------|------|-----------|-------|
| red | ShortSqueezeScreener | src/teams/red/screener.py | red_team | short-squeeze-sniper |
| orange | GammaSqueezeScreener | src/teams/orange/screener.py | orange_team | gamma-flow-hunter |
| yellow | SocialSentimentScreener | src/teams/yellow/screener.py | yellow_team | social-sentiment-quant |
| green | LowFloatBreakoutScreener | src/teams/green/screener.py | green_team | low-float-breakout |
| blue | MomentumCatalystScreener | src/teams/blue/screener.py | blue_team | momentum-catalyst-fusion |

## Agent Config Conventions (v0.1.1)
- All agents: `inclusion: always`, `memory: project`
- Analysis agents: `tools: Read, Grep, Glob, Bash, WebSearch, WebFetch, Task` (no Write/Edit)
- Analysis agents: `maxTurns: 25`
- SDE-Team: all tools, `maxTurns: 80`
- Agent colors MUST match Python team colors
- CLAUDE.md at project root is the shared context for all agents

## Known Bugs Fixed (v0.1.2, 2026-02-24)
- `detect_breakout()` used `abs()` on price change — caught downside crashes as "breakouts". Fixed: now requires `price_change > 0`.
- Green team had no SPAC/shell company filter — SPACs with NAV-anchored pricing produced false positives. Fixed: `_EXCLUDED_INDUSTRIES` frozenset.
- Yellow team silently returned None when Reddit API keys missing — all `sentiment_polarity` scores were 0 with no warning. Fixed: `_check_reddit_credentials()` logs WARNING once.

## Agent Analysis Patterns (from first production run)
- Red team: yfinance ADR short interest data can be wrong for large-caps (ABX 43% SI implausible)
- Green team: Of 6 candidates, only 1 showed genuine accumulation; `technical_setup` is most reliable sub-score
- Yellow team: Without Reddit API, scoring ceiling drops to 75/100 (sentiment_polarity=0 always)
- Blue team: `min_momentum_score: 60` threshold is critical gatekeeper — 3 of 6 top candidates failed momentum veto

## Environment Notes
- Ubuntu 24.04 on WSL2, Python 3.12.3
- Must use venv (externally-managed-environment restriction)
- Activate: `source /root/Pi/SAnalysis/.venv/bin/activate`
