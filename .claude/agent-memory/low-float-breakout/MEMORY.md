# Low Float Breakout Memory

## Code Bridge
- Python: `src/teams/green/screener.py` -> `LowFloatBreakoutScreener`
- Config: `config/default.yaml` -> `green_team`
- Scoring: float_tightness, volume_explosion, technical_setup, breakout_quality (each 0-25)
- Run: `python main.py --teams green`
- Cache: info cached as JSON at `data/cache/info_{hash}.json` with key = ticker symbol

## Known Code Bugs (2026-02-24)
- `detect_breakout()` in technical.py line 213: FIXED in code (directional filter added), but still uses abs() pattern in memory -- verify on next run.
- SPAC exclusion: `_EXCLUDED_INDUSTRIES` only has 2 entries ("Shell Companies", "Blank Checks"). Need quoteType + company name pattern matching.
- Post-reverse-split volume distortion: No detection mechanism. Need to check "Stock Splits" column in hist data.
- Volume-price direction correlation missing: high RVOL + negative price change should be penalized in `_score_volume_explosion`.

## Code Review Findings (2026-02-24)
- **API waste**: Each ticker makes 3 separate `get_history` calls (6mo, 1mo, 3mo) + 1 `get_ticker_info`. Can reduce to 1+1 by passing data down.
- **MACD not used**: `_score_technical_setup` claims MACD in docstring but never calls `technical.macd()`. 4 points of scoring info lost.
- **Dead code**: `rvol >= 1.5` branch in `_score_volume_explosion` is unreachable because `analyze()` pre-filters at min_rvol=2.0.
- **float unknown = 5pts**: Too generous. Should be 2pts max for unknown float.
- **No market cap filter**: System spec says $50M-$2B but code doesn't check `marketCap`.
- **52w high proximity overweighted**: 8pts (32% of breakout_quality) for being near 52w high; should be 5pts.
- **VWAP on daily data**: Cumulative VWAP over 6mo is just volume-weighted average price, not intraday VWAP. 5pts overweighted.

## Analysis Patterns Discovered
- Earnings-day crashes (CTEV -41%, BOOM -33%) trigger false breakout flags due to abs() in detect_breakout()
- Block trades on SPACs (CHEC: single-print 300K volume) inflate RVOL without price discovery
- Post-reverse-split stocks (ADVB 1:20, ALUR 1:25) show distorted float/volume metrics for 2-4 weeks
- technical_setup score is the most reliable sub-score for identifying genuine accumulation (CVKD=21/25 was the only legitimate candidate)
- float_tightness=25 does not guarantee quality -- both ALUR and ADVB scored 25 but were in active decline

## Screening Quality Notes
- Of 6 top candidates on 2026-02-24, only 1 (CVKD) showed legitimate accumulation characteristics
- 2 were earnings crashes, 1 was post-split chaos, 1 was SPAC block trade, 1 was distribution
- High RVOL without positive price direction = selling pressure, not breakout potential
