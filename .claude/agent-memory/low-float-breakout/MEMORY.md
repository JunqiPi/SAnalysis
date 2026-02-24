# Low Float Breakout Memory

## Code Bridge
- Python: `src/teams/green/screener.py` -> `LowFloatBreakoutScreener`
- Config: `config/default.yaml` -> `green_team`
- Scoring: float_tightness, volume_explosion, technical_setup, breakout_quality (each 0-25)
- Run: `python main.py --teams green`
- Cache: info cached as JSON at `data/cache/info_{hash}.json` with key = ticker symbol

## Known Code Bugs (2026-02-24)
- `detect_breakout()` in `/root/Pi/SAnalysis/src/utils/technical.py` line 213 uses `abs()` on price change -- catches downside crashes as "breakouts". Must add directional filter.
- No SPAC/shell company exclusion in screener -- SPACs with NAV-anchored prices produce false positives.
- Post-reverse-split volume distortion: RVOL calculation mixes pre/post-split volumes, inflating readings.
- Volume-price direction correlation missing: high RVOL + negative price change should be penalized.

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
