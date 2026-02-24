# Short Squeeze Sniper -- Agent Memory

## Key File Paths
- Screener code: `/root/Pi/SAnalysis/src/teams/red/screener.py`
- Config: `/root/Pi/SAnalysis/config/default.yaml` (red_team section)
- Data types: `/root/Pi/SAnalysis/src/core/data_types.py`
- Market data wrapper: `/root/Pi/SAnalysis/src/utils/market_data.py`
- Output: `/root/Pi/SAnalysis/data/output/watchlist_*.csv`
- Cache: `/root/Pi/SAnalysis/data/cache/`

## Scoring Tiers (from code, verified 2026-02-24)
- short_intensity: >=40%=25, >=30%=22, >=20%=18, >=15%=14, >=10%=10
- cover_difficulty: DTC>=10=12, >=7=10, >=5=8, >=3=5 | float<10M=8, <20M=6, <50M=4, <100M=2 | PCR>2.0=5, >1.5=3, >1.0=1.5
- catalyst: earnings<=7d=12, <=14d=8, <=30d=4 | RVOL>=5=10, >=3=7, >=2=4, >=1.5=2
- technical: RSI 50-70=8, 40-50=5, <40=2 | price>MA20=5 | ret5d 5-30%=7, 0-5%=3, >30%=2 | MACD bullish=5

## Known Data Issues
- yfinance short interest has ~2 week lag (FINRA semi-monthly)
- Borrow fee NOT available in Phase 1 (free tier)
- ADR/cross-listed stocks (e.g., ABX/Barrick Gold) may report INCORRECT short float via yfinance
- Low-volume option stocks can have extreme P/C ratios from single block trades (e.g., AAON P/C=15.44)
- P/C ratio is computed from nearest expiration only -- may not represent full options positioning

## Analysis Patterns
- Always verify anomalous SI readings for large-caps (>$10B market cap)
- Multi-team appearance (red+orange+blue) does NOT automatically mean better candidate
- AMC squeeze thesis is dead as of Feb 2026: diluted float, DTC 3.03, technicals 2/25
- CFA four-factor test is critical gatekeeper: speculative/unproven factor filters out quality companies being shorted on valuation

## Pipeline Notes
- CSV output has all teams merged; filter by red_score column for red team results
- Composite score weights: red x1.0, orange x1.0, yellow x0.8, green x1.0, blue x0.9
- Run command: `source /root/Pi/SAnalysis/.venv/bin/activate && python main.py --teams red`
