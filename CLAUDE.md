# SAnalysis — Meme Stock Analysis Platform

> Phase 1: Zero-Cost Prototype (v0.1.0, 2026-02-23)
> Python 3.12 · venv at `.venv/` · Ubuntu 24.04 / WSL2

## Quick Start

```bash
source /root/Pi/SAnalysis/.venv/bin/activate
python main.py                          # Run all 5 teams
python main.py --teams red green        # Run specific teams
python main.py --tickers GME AMC TSLA   # Analyze specific tickers
python main.py --no-parallel            # Sequential mode (debug)
python main.py --top 30                 # Show top 30 results
```

## Architecture

```
src/
├── core/
│   ├── base.py          # BaseScreener: fetch_candidates() + analyze(ticker) contract
│   ├── config.py        # Singleton YAML + env var config loader
│   ├── cache.py         # File-based parquet/JSON cache with TTL
│   └── data_types.py    # ScreenResult, ShortData, OptionsSnapshot, etc.
├── utils/
│   ├── market_data.py   # Centralized yfinance wrapper (cached)
│   ├── technical.py     # pandas_ta with manual fallbacks (RSI, MACD, BB, OBV, VWAP, ATR)
│   └── finviz_scraper.py# HTML parser for Finviz free tier
├── teams/               # ← Each team is a BaseScreener subclass
│   ├── red/screener.py
│   ├── orange/screener.py
│   ├── yellow/screener.py
│   ├── green/screener.py
│   └── blue/screener.py
├── pipeline/
│   └── orchestrator.py  # ThreadPoolExecutor, merge, weighted composite score
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
| 🟧 SDE-Team | N/A (code writer) | N/A | N/A | `SDE-Team` | N/A |

## Scoring Model

- Each team: 4 factors × 25 points = **100 max per team**
- All teams output `ScreenResult` dataclass (defined in `src/core/data_types.py`)
- Orchestrator computes weighted composite: `red×1.0, orange×1.0, yellow×0.8, green×1.0, blue×0.9`
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
Optional: praw (Reddit API — needs keys in secrets.yaml)

## Agent Instructions

**Analysis Agents (5 teams)**: When asked to analyze stocks, you MUST:
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
