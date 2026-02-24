# Gamma Flow Hunter Memory

## Code Bridge
- Python: `src/teams/orange/screener.py` → `GammaSqueezeScreener`
- Config: `config/default.yaml` → `orange_team`
- Scoring: options_activity, gamma_exposure, iv_dynamics, oi_setup (each 0-25)
- Run: `python main.py --teams orange`

## Known Code Issues (2026-02-24 Review)
- See `code-review-findings.md` for full details
- CRITICAL: GEX sign convention is inverted in `_score_gex` - positive net_gex should score high (dealer short gamma)
- CRITICAL: `_find_gex_flip` computes per-strike not cumulative flip
- OTM call detection uses median strike, should use spot price
- 4x iterrows() needs vectorization
- BBBY delisted, remove from candidates
- No IV Rank, only absolute IV - bad for cross-stock comparison
