# Code Review Findings - Orange Team Screener

## Date: 2026-02-24

## P0 Issues (Must Fix)
1. **GEX sign convention inverted** in `_score_gex`: positive net_gex = dealer short gamma (should get high score), but code gives 12pts to negative net_gex
2. **`_find_gex_flip` uses per-strike net, not cumulative** - standard gamma flip is cumulative GEX sign change
3. **BBBY delisted** in candidate list (line 54)
4. **`_oi_concentration_proxy` dimension mismatch** - returns raw OI counts vs gamma*OI*100*spot when greeks available

## P1 Issues
1. 4x `iterrows()` at lines 151,161,193,198 - vectorize with pandas ops
2. Only analyzes single expiry - need multi-expiry GEX overlay
3. No IV Rank/Percentile - only absolute IV levels
4. OTM call definition uses median strike instead of spot price (line 274)
5. PCR only volume-based, no OI-based PCR

## Key Patterns
- yfinance gamma field may be NaN for illiquid strikes - always fillna(0)
- Extreme IV (>500%) from deep OTM illiquid contracts skews averages
- Config params `spot_price_range_pct` and `strike_step_count` are unused
