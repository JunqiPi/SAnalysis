"""
Orange Team: Gamma Squeeze & Options Flow Hunter

Phase 1 data sources:
  - yfinance options module (chains, OI, volume, IV, greeks)

Scoring model (0-100):
  - Options Activity    (0-25): Total volume, unusual volume/OI ratio
  - Gamma Exposure      (0-25): Estimated GEX, concentration near spot
  - IV Dynamics         (0-25): IV level, IV rank proxy, skew
  - Open Interest Setup (0-25): OI concentration, put/call OI ratio, OI changes
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from src.core.base import BaseScreener
from src.core.data_types import OptionsSnapshot, ScreenResult
from src.utils import market_data

logger = logging.getLogger(__name__)


class GammaSqueezeScreener(BaseScreener):
    """Orange Team screener: identifies gamma squeeze and unusual options flow."""

    @property
    def team_name(self) -> str:
        return "orange"

    def _team_cfg(self):
        return self.cfg["orange_team"]

    # ------------------------------------------------------------------
    # Candidate discovery
    # ------------------------------------------------------------------

    def fetch_candidates(self) -> list[str]:
        """Return tickers with active options markets.

        Phase 1: uses a curated list of liquid optionable tickers.
        Phase 2+: will scan option volume screeners.
        """
        # Curated list of meme/squeeze-adjacent optionable tickers
        return [
            "GME", "AMC", "TSLA", "NVDA", "AAPL", "PLTR", "SOFI",
            "NIO", "RIVN", "LCID", "CLOV", "FUBO", "MARA",
            "RIOT", "COIN", "HOOD", "SNAP", "PINS", "RBLX",
            "DKNG", "SPCE", "UPST", "SMCI", "ARM",
        ]

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def _get_near_term_snapshot(self, ticker: str) -> Optional[OptionsSnapshot]:
        """Fetch option chain for the nearest expiration within N days."""
        expirations = market_data.get_options_expirations(ticker)
        if not expirations:
            return None

        cfg = self._team_cfg()
        max_days = cfg.get("near_expiry_days", 30)
        now = datetime.now(timezone.utc).date()

        target_exp = None
        for exp_str in expirations:
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            delta = (exp_date - now).days
            if 0 < delta <= max_days:
                target_exp = exp_str
                break

        if target_exp is None and expirations:
            target_exp = expirations[0]  # Fallback to nearest available

        if target_exp is None:
            return None

        calls, puts = market_data.get_options_chain(ticker, target_exp)
        if calls.empty and puts.empty:
            return None

        call_vol = int(calls["volume"].sum()) if "volume" in calls.columns else 0
        put_vol = int(puts["volume"].sum()) if "volume" in puts.columns else 0
        call_oi = int(calls["openInterest"].sum()) if "openInterest" in calls.columns else 0
        put_oi = int(puts["openInterest"].sum()) if "openInterest" in puts.columns else 0

        pcr = (put_vol / call_vol) if call_vol > 0 else 0.0
        pcr_oi = (put_oi / call_oi) if call_oi > 0 else 0.0

        return OptionsSnapshot(
            ticker=ticker,
            expiration=target_exp,
            calls=calls,
            puts=puts,
            total_call_volume=call_vol,
            total_put_volume=put_vol,
            total_call_oi=call_oi,
            total_put_oi=put_oi,
            put_call_ratio=pcr,
            put_call_ratio_oi=pcr_oi,
        )

    # ------------------------------------------------------------------
    # GEX estimation (simplified)
    # ------------------------------------------------------------------

    def _estimate_gex(self, snap: OptionsSnapshot, spot: float) -> dict:
        """Estimate Gamma Exposure (GEX) from option chain data.

        This is a simplified GEX calculation using available yfinance data.
        Real GEX requires dealer positioning data (Phase 2+ via SpotGamma).

        Approximation:
            GEX_per_strike = Gamma * OI * 100 * spot_price
            Net GEX = sum(call_GEX) - sum(put_GEX)

        Sign convention (assumes dealers are net short calls / net long puts):
            net_gex > 0 → dealers short gamma → amplifies moves (squeeze-prone)
            net_gex < 0 → dealers long gamma → dampens moves
        """
        result = {
            "net_gex": 0.0,
            "max_gamma_strike": None,
            "gex_flip_strike": None,
            "call_gex_total": 0.0,
            "put_gex_total": 0.0,
        }

        calls = snap.calls
        puts = snap.puts

        has_gamma = "gamma" in calls.columns if not calls.empty else False

        if not has_gamma:
            return self._oi_concentration_proxy(snap, spot)

        # Vectorized call GEX: gamma * OI * 100 * spot per strike
        c_gamma = calls["gamma"].fillna(0)
        c_oi = calls["openInterest"].fillna(0)
        c_gex_per_strike = c_gamma * c_oi * 100 * spot
        call_gex = float(c_gex_per_strike.sum())

        # Max gamma strike (strongest gamma pin / magnet effect)
        max_gamma_strike = spot
        if not c_gex_per_strike.empty and c_gex_per_strike.max() > 0:
            max_idx = c_gex_per_strike.idxmax()
            max_gamma_strike = float(calls.loc[max_idx, "strike"])

        # Vectorized put GEX
        put_gex = 0.0
        if not puts.empty and "gamma" in puts.columns:
            p_gamma = puts["gamma"].fillna(0)
            p_oi = puts["openInterest"].fillna(0)
            p_gex_per_strike = p_gamma * p_oi * 100 * spot
            put_gex = float(p_gex_per_strike.sum())

        net_gex = call_gex - put_gex

        # GEX flip: strike where cumulative net GEX crosses zero
        flip_strike = self._find_gex_flip(calls, puts, spot)

        result["net_gex"] = net_gex
        result["call_gex_total"] = call_gex
        result["put_gex_total"] = put_gex
        result["max_gamma_strike"] = max_gamma_strike
        result["gex_flip_strike"] = flip_strike

        return result

    def _find_gex_flip(
        self, calls: pd.DataFrame, puts: pd.DataFrame, spot: float,
    ) -> Optional[float]:
        """Find the strike where cumulative net GEX crosses zero.

        The GEX flip point is where *cumulative* (not per-strike) net GEX
        changes sign, representing the price level where dealer hedging
        switches from dampening to amplifying moves.
        """
        if calls.empty or "gamma" not in calls.columns:
            return None

        # Vectorized per-strike call GEX (groupby handles duplicate strikes)
        c = calls.assign(
            gex=calls["gamma"].fillna(0) * calls["openInterest"].fillna(0),
        )
        c_by_strike = c.groupby("strike")["gex"].sum()

        # Vectorized per-strike put GEX
        p_by_strike = pd.Series(dtype=float)
        if not puts.empty and "gamma" in puts.columns:
            p = puts.assign(
                gex=puts["gamma"].fillna(0) * puts["openInterest"].fillna(0),
            )
            p_by_strike = p.groupby("strike")["gex"].sum()

        # Net GEX per strike, sorted ascending
        all_strikes = sorted(set(c_by_strike.index) | set(p_by_strike.index))
        if len(all_strikes) < 2:
            return None

        net_per_strike = pd.Series(
            [c_by_strike.get(s, 0.0) - p_by_strike.get(s, 0.0) for s in all_strikes],
            index=all_strikes,
        )

        # Cumulative sum — flip is where cumulative crosses zero
        cumulative = net_per_strike.cumsum()
        sign_changes = (cumulative * cumulative.shift(1)) < 0
        if sign_changes.any():
            return float(sign_changes.idxmax())

        return None

    def _oi_concentration_proxy(self, snap: OptionsSnapshot, spot: float) -> dict:
        """When greeks are unavailable, use OI concentration as GEX proxy."""
        result = {
            "net_gex": 0.0,
            "max_gamma_strike": None,
            "gex_flip_strike": None,
            "call_gex_total": 0.0,
            "put_gex_total": 0.0,
        }

        calls = snap.calls
        if not calls.empty and "openInterest" in calls.columns and "strike" in calls.columns:
            max_oi_idx = calls["openInterest"].idxmax()
            if pd.notna(max_oi_idx):
                result["max_gamma_strike"] = float(calls.loc[max_oi_idx, "strike"])
                result["call_gex_total"] = float(calls["openInterest"].sum())

        puts = snap.puts
        if not puts.empty and "openInterest" in puts.columns:
            result["put_gex_total"] = float(puts["openInterest"].sum())

        result["net_gex"] = result["call_gex_total"] - result["put_gex_total"]
        return result

    # ------------------------------------------------------------------
    # Unusual options activity detection
    # ------------------------------------------------------------------

    def _detect_unusual_activity(self, snap: OptionsSnapshot, spot: float) -> dict:
        """Detect unusual options activity patterns.

        Key signals:
          - Volume >> OI (new positions being opened aggressively)
          - Concentrated OTM call buying (squeeze anticipation)
          - Put volume collapse (bears retreating)
        """
        cfg = self._team_cfg()
        unusual_ratio = cfg.get("unusual_volume_ratio", 3.0)
        result = {
            "has_unusual_calls": False,
            "has_unusual_puts": False,
            "max_vol_oi_ratio": 0.0,
            "otm_call_concentration": 0.0,
            "unusual_strikes": [],
        }

        calls = snap.calls
        if calls.empty or "volume" not in calls.columns or "openInterest" not in calls.columns:
            return result

        # Find strikes where volume >> OI
        calls_valid = calls[(calls["openInterest"] > 0) & (calls["volume"] > 0)].copy()
        if not calls_valid.empty:
            calls_valid["vol_oi_ratio"] = calls_valid["volume"] / calls_valid["openInterest"]
            unusual = calls_valid[calls_valid["vol_oi_ratio"] >= unusual_ratio]
            if not unusual.empty:
                result["has_unusual_calls"] = True
                result["max_vol_oi_ratio"] = float(unusual["vol_oi_ratio"].max())
                result["unusual_strikes"] = unusual["strike"].tolist()

        # OTM call concentration (calls with strike above spot price)
        if "strike" in calls.columns and len(calls) > 0 and spot > 0:
            otm_calls = calls[calls["strike"] > spot]
            total_vol = calls["volume"].sum()
            if total_vol > 0:
                otm_vol = otm_calls["volume"].sum()
                result["otm_call_concentration"] = float(otm_vol / total_vol)

        return result

    # ------------------------------------------------------------------
    # IV analysis
    # ------------------------------------------------------------------

    def _analyze_iv(self, snap: OptionsSnapshot, spot: float) -> dict:
        """Analyze implied volatility dynamics."""
        result = {
            "avg_call_iv": None,
            "avg_put_iv": None,
            "atm_iv": None,
            "iv_skew": None,   # Put IV - Call IV at similar strikes
        }

        calls = snap.calls
        puts = snap.puts

        iv_col = "impliedVolatility"

        if not calls.empty and iv_col in calls.columns:
            valid_iv = calls[calls[iv_col] > 0][iv_col]
            if not valid_iv.empty:
                result["avg_call_iv"] = float(valid_iv.mean())

        if not puts.empty and iv_col in puts.columns:
            valid_iv = puts[puts[iv_col] > 0][iv_col]
            if not valid_iv.empty:
                result["avg_put_iv"] = float(valid_iv.mean())

        # ATM IV: closest strike to spot
        if not calls.empty and "strike" in calls.columns and iv_col in calls.columns:
            atm_idx = (calls["strike"] - spot).abs().idxmin()
            if pd.notna(atm_idx):
                atm_iv = calls.loc[atm_idx, iv_col]
                if atm_iv and atm_iv > 0:
                    result["atm_iv"] = float(atm_iv)

        # IV skew
        if result["avg_put_iv"] is not None and result["avg_call_iv"] is not None:
            result["iv_skew"] = result["avg_put_iv"] - result["avg_call_iv"]

        return result

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_options_activity(self, snap: OptionsSnapshot, unusual: dict) -> float:
        """Score 0-25: How active and unusual is the options flow?"""
        score = 0.0
        cfg = self._team_cfg()
        min_vol = cfg.get("min_option_volume", 1000)

        total_vol = snap.total_call_volume + snap.total_put_volume
        if total_vol < min_vol:
            return 0.0

        # Volume level
        if total_vol >= 50000:
            score += 8.0
        elif total_vol >= 20000:
            score += 6.0
        elif total_vol >= 5000:
            score += 4.0
        else:
            score += 2.0

        # Unusual activity
        if unusual["has_unusual_calls"]:
            ratio = unusual["max_vol_oi_ratio"]
            if ratio >= 10:
                score += 10.0
            elif ratio >= 5:
                score += 7.0
            elif ratio >= 3:
                score += 4.0

        # OTM call concentration (squeeze-anticipation signal)
        otm_conc = unusual["otm_call_concentration"]
        if otm_conc > 0.7:
            score += 7.0
        elif otm_conc > 0.5:
            score += 4.0
        elif otm_conc > 0.3:
            score += 2.0

        return min(25.0, score)

    def _score_gex(self, gex: dict, spot: float) -> float:
        """Score 0-25: Gamma exposure setup with magnitude normalization.

        Sign convention: net_gex = call_gex - put_gex.
        Dealers are assumed net short calls / long puts, so:
          net_gex > 0 → dealer gamma is negative → amplifies moves → squeeze-prone
          net_gex < 0 → dealer gamma is positive → dampens moves

        Magnitude matters: a tiny positive GEX is less meaningful than a large one.
        We normalize relative to total GEX to gauge how imbalanced the exposure is.
        """
        score = 0.0
        net = gex.get("net_gex", 0)
        call_gex = gex.get("call_gex_total", 0)
        put_gex = gex.get("put_gex_total", 0)
        total_gex = abs(call_gex) + abs(put_gex)

        # Positive net GEX: dealers are short gamma -> amplifies moves
        if net > 0:
            # Magnitude normalization: how strongly is the GEX skewed?
            if total_gex > 0:
                imbalance = abs(net) / total_gex  # 0 to 1
                if imbalance >= 0.7:
                    score += 14.0  # Extreme: heavily short gamma
                elif imbalance >= 0.4:
                    score += 11.0  # Strong imbalance
                else:
                    score += 8.0   # Mild positive (some squeeze potential)
            else:
                score += 8.0
        elif net == 0:
            score += 3.0  # Neutral: balanced hedging
        else:
            # Negative GEX: dealers long gamma -> dampens moves
            score += 1.0

        # Max gamma strike proximity to spot (pin risk / magnet effect)
        mg_strike = gex.get("max_gamma_strike")
        if mg_strike and spot > 0:
            proximity = abs(mg_strike - spot) / spot
            if proximity < 0.02:
                score += 7.0  # Very close: strong pin or breakout potential
            elif proximity < 0.05:
                score += 4.0
            elif proximity < 0.10:
                score += 2.0

        # GEX flip presence near spot (indicates regime boundary)
        flip = gex.get("gex_flip_strike")
        if flip is not None and spot > 0:
            flip_distance = abs(flip - spot) / spot
            if flip_distance < 0.05:
                score += 4.0  # Flip point near spot = high transition risk
            else:
                score += 2.0  # Flip exists but further away

        return min(25.0, score)

    def _score_iv(self, iv_data: dict) -> float:
        """Score 0-25: IV dynamics and skew analysis."""
        score = 0.0

        atm_iv = iv_data.get("atm_iv")
        if atm_iv is not None:
            # High IV = expectation of big move
            if atm_iv >= 1.5:
                score += 10.0
            elif atm_iv >= 1.0:
                score += 8.0
            elif atm_iv >= 0.6:
                score += 5.0
            elif atm_iv >= 0.3:
                score += 2.0

        # IV skew: positive = puts more expensive = hedging demand
        skew = iv_data.get("iv_skew")
        if skew is not None:
            if skew > 0.2:
                score += 8.0  # Heavy put hedging (potential short squeeze fuel)
            elif skew > 0.1:
                score += 5.0
            elif skew > 0:
                score += 2.0
            elif skew < -0.1:
                score += 7.0  # Call IV premium = aggressive call buying

        return min(25.0, score)

    def _score_oi_setup(self, snap: OptionsSnapshot) -> float:
        """Score 0-25: Open interest setup quality.

        Uses both volume-based and OI-weighted put/call ratios for a
        more stable signal than volume alone (which is noisy intraday).
        """
        score = 0.0

        total_oi = snap.total_call_oi + snap.total_put_oi
        if total_oi == 0:
            return 0.0

        # High absolute OI = many positions to unwind (0-7)
        if total_oi >= 500000:
            score += 7.0
        elif total_oi >= 100000:
            score += 5.0
        elif total_oi >= 50000:
            score += 3.0
        else:
            score += 1.0

        # Call OI dominance (bullish positioning, 0-6)
        if snap.total_call_oi > 0:
            call_oi_ratio = snap.total_call_oi / total_oi
            if call_oi_ratio > 0.65:
                score += 6.0  # Heavy call OI = dealer short gamma
            elif call_oi_ratio > 0.55:
                score += 3.0

        # OI-weighted P/C ratio: more stable than volume-only (0-5)
        # Uses the pre-computed put_call_ratio_oi from OptionsSnapshot
        pcr_oi = snap.put_call_ratio_oi
        if pcr_oi > 2.0:
            score += 5.0  # Extreme put hedging (high demand for downside protection)
        elif pcr_oi < 0.3:
            score += 5.0  # Extreme call dominance (squeeze anticipation)
        elif pcr_oi > 1.5:
            score += 3.0  # Elevated hedging
        elif pcr_oi < 0.5:
            score += 3.0  # Bullish lean

        # Volume relative to OI (new positioning intensity, 0-4)
        total_vol = snap.total_call_volume + snap.total_put_volume
        if total_oi > 0:
            vol_oi = total_vol / total_oi
            if vol_oi > 0.5:
                score += 4.0
            elif vol_oi > 0.3:
                score += 2.0

        return min(25.0, score)

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    def analyze(self, ticker: str) -> ScreenResult | None:
        """Full analysis pipeline for a single ticker."""
        snap = self._get_near_term_snapshot(ticker)
        if snap is None:
            logger.debug("[orange] No options data for %s, skipping.", ticker)
            return None

        spot = market_data.get_current_price(ticker)
        if spot is None or spot <= 0:
            return None

        gex = self._estimate_gex(snap, spot)
        unusual = self._detect_unusual_activity(snap, spot)
        iv_data = self._analyze_iv(snap, spot)

        s1 = self._score_options_activity(snap, unusual)
        s2 = self._score_gex(gex, spot)
        s3 = self._score_iv(iv_data)
        s4 = self._score_oi_setup(snap)
        total = s1 + s2 + s3 + s4

        return ScreenResult(
            ticker=ticker,
            team="orange",
            score=total,
            signals={
                "options_activity": s1,
                "gamma_exposure": s2,
                "iv_dynamics": s3,
                "oi_setup": s4,
                "net_gex": gex.get("net_gex", 0),
                "atm_iv": iv_data.get("atm_iv", 0),
                "put_call_ratio": snap.put_call_ratio,
                "put_call_ratio_oi": snap.put_call_ratio_oi,
                "total_volume": snap.total_call_volume + snap.total_put_volume,
                "max_vol_oi_ratio": unusual.get("max_vol_oi_ratio", 0),
            },
            metadata={
                "expiration": snap.expiration,
                "spot_price": spot,
                "max_gamma_strike": gex.get("max_gamma_strike"),
                "gex_flip_strike": gex.get("gex_flip_strike"),
                "unusual_strikes": unusual.get("unusual_strikes", []),
                "iv_skew": iv_data.get("iv_skew"),
            },
        )
