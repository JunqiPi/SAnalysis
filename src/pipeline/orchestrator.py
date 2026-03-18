"""
Pipeline Orchestrator: coordinates all five team screeners.

Runs each team's screening pipeline, merges results into a unified
watchlist with composite scoring, and outputs to CSV / console.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

from src.core.base import BaseScreener
from src.core.config import get_config
from src.core.data_types import ScreenResult, results_to_dataframe

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Lazy import map: only instantiate screeners that are actually requested.
# This avoids importing all team modules (and their dependencies) upfront.
_SCREENER_REGISTRY: dict[str, str] = {
    "red": "src.teams.red.screener.ShortSqueezeScreener",
    "orange": "src.teams.orange.screener.GammaSqueezeScreener",
    "yellow": "src.teams.yellow.screener.SocialSentimentScreener",
    "green": "src.teams.green.screener.LowFloatBreakoutScreener",
    "blue": "src.teams.blue.screener.MomentumCatalystScreener",
}


def _create_screener(qualified_name: str) -> BaseScreener:
    """Dynamically import and instantiate a screener class by dotted path."""
    module_path, class_name = qualified_name.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()

# Fallback team weights used when config/default.yaml does not define
# orchestrator.team_weights (or a caller does not supply explicit overrides).
_FALLBACK_TEAM_WEIGHTS: dict[str, float] = {
    "red": 1.0,
    "orange": 1.0,
    "yellow": 0.8,     # Sentiment is noisier, slightly lower weight
    "green": 1.0,
    "blue": 0.9,
}

# Display metadata for each team: Chinese name, icon, weight label, and sub-factor mapping
TEAM_DISPLAY = {
    "red": {
        "name": "空头挤压狙击队",
        "icon": "🔴",
        "weight_label": "红",
        "factors": [
            ("做空强度", "short_intensity"),
            ("回补难度", "cover_difficulty"),
            ("催化剂临近", "catalyst_proximity"),
            ("技术动量", "technical_momentum"),
        ],
    },
    "orange": {
        "name": "Gamma挤压猎手",
        "icon": "🟠",
        "weight_label": "橙",
        "factors": [
            ("期权活跃度", "options_activity"),
            ("Gamma敞口", "gamma_exposure"),
            ("隐含波动率", "iv_dynamics"),
            ("持仓结构", "oi_setup"),
        ],
    },
    "yellow": {
        "name": "社交情绪侦察队",
        "icon": "🟡",
        "weight_label": "黄",
        "factors": [
            ("提及频率", "mention_frequency"),
            ("情绪极性", "sentiment_polarity"),
            ("情绪动量", "sentiment_momentum"),
            ("信号质量", "signal_quality"),
        ],
    },
    "green": {
        "name": "低流通突破特战队",
        "icon": "🟢",
        "weight_label": "绿",
        "factors": [
            ("流通盘紧度", "float_tightness"),
            ("量能爆发", "volume_explosion"),
            ("技术面", "technical_setup"),
            ("突破质量", "breakout_quality"),
        ],
    },
    "blue": {
        "name": "动量催化复合精英队",
        "icon": "🔵",
        "weight_label": "蓝",
        "factors": [
            ("价格动量", "price_momentum"),
            ("催化剂临近", "catalyst_proximity"),
            ("财务质量", "financial_quality"),
            ("市场环境", "market_regime"),
        ],
    },
}

# Canonical team order for display
TEAM_ORDER = ["red", "orange", "yellow", "green", "blue"]


class PipelineOrchestrator:
    """Master orchestrator for the five-team screening pipeline.

    Usage::

        orchestrator = PipelineOrchestrator()
        watchlist = orchestrator.run()
        orchestrator.save_results(watchlist)
    """

    def __init__(
        self,
        teams: Sequence[str] | None = None,
        team_weights: dict[str, float] | None = None,
        ai_rescore: bool = False,
    ) -> None:
        """
        Args:
            teams: Which teams to run. None = all. E.g. ["red", "green"].
            team_weights: Override team weights for composite scoring.
            ai_rescore: Enable Claude AI qualitative re-scoring.
        """
        self.cfg = get_config()
        self._ai_client = None

        # Resolve AI re-scoring: CLI flag overrides YAML config default
        ai_enabled = ai_rescore or bool(
            self.cfg.get_nested("ai_rescore", "enabled", default=False)
        )
        if ai_enabled:
            try:
                from src.ai.client import AIClient
                client = AIClient.instance()
                if client.is_available():
                    self._ai_client = client
                    logger.info("AI re-scoring enabled.")
                else:
                    logger.warning("AI re-scoring requested but not available. Using quant-only.")
            except Exception:
                logger.exception("Failed to initialize AI client. Using quant-only.")

        # Priority: explicit arg > config YAML > hardcoded fallback
        if team_weights is not None:
            self.team_weights = team_weights
        else:
            cfg_weights = self.cfg.get_nested("orchestrator", "team_weights")
            if isinstance(cfg_weights, dict) and cfg_weights:
                self.team_weights = {
                    k: float(v) for k, v in cfg_weights.items()
                }
            else:
                self.team_weights = _FALLBACK_TEAM_WEIGHTS

        # Only instantiate requested teams (lazy import for faster startup)
        requested = teams or list(_SCREENER_REGISTRY.keys())
        self.screeners: dict[str, BaseScreener] = {}
        for name in requested:
            if name not in _SCREENER_REGISTRY:
                logger.warning("Unknown team '%s', skipping.", name)
                continue
            try:
                self.screeners[name] = _create_screener(_SCREENER_REGISTRY[name])
            except Exception:
                logger.exception("Failed to initialize team '%s'.", name)

    def run(
        self,
        tickers: Sequence[str] | None = None,
        parallel: bool = True,
    ) -> pd.DataFrame:
        """Execute all configured team screeners and produce a unified watchlist.

        Args:
            tickers: If provided, all teams analyze these specific tickers
                     instead of running their own candidate discovery.
            parallel: Run teams in parallel threads (default True).

        Returns:
            DataFrame with columns: ticker, composite_score, team scores,
            signal details, and metadata.
        """
        all_results: list[ScreenResult] = []

        if parallel:
            max_workers = self.cfg.get_nested("general", "max_workers", default=4)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self._run_team, name, screener, tickers): name
                    for name, screener in self.screeners.items()
                }
                for future in as_completed(futures):
                    team_name = futures[future]
                    try:
                        results = future.result()
                        all_results.extend(results)
                        logger.info(
                            "Team [%s] completed: %d results.", team_name, len(results),
                        )
                    except Exception:
                        logger.exception("Team [%s] failed.", team_name)
        else:
            for name, screener in self.screeners.items():
                try:
                    results = self._run_team(name, screener, tickers)
                    all_results.extend(results)
                    logger.info(
                        "Team [%s] completed: %d results.", name, len(results),
                    )
                except Exception:
                    logger.exception("Team [%s] failed.", name)

        if not all_results:
            logger.warning("No results from any team.")
            return pd.DataFrame()

        # Build per-team DataFrames
        team_dfs = self._build_team_dataframes(all_results)

        # AI re-scoring (only when enabled + client available)
        if self._ai_client is not None:
            team_dfs = self._apply_ai_rescoring(team_dfs, all_results)

        # Merge into unified watchlist with composite scoring
        watchlist = self._merge_and_score(team_dfs)
        return watchlist

    def _run_team(
        self,
        name: str,
        screener: BaseScreener,
        tickers: Sequence[str] | None,
    ) -> list[ScreenResult]:
        """Run a single team's screener with timing."""
        t0 = time.monotonic()
        logger.info("Starting team [%s]...", name)
        results = screener.run(tickers=tickers)
        elapsed = time.monotonic() - t0
        logger.info(
            "Team [%s] finished in %.1fs: %d results.",
            name, elapsed, len(results),
        )
        return results

    def _build_team_dataframes(
        self, results: list[ScreenResult],
    ) -> dict[str, pd.DataFrame]:
        """Group results by team and convert to DataFrames."""
        by_team: dict[str, list[ScreenResult]] = {}
        for r in results:
            by_team.setdefault(r.team, []).append(r)

        team_dfs = {}
        for team, team_results in by_team.items():
            df = results_to_dataframe(team_results)
            if not df.empty:
                # Prefix team-specific signal columns
                rename_map = {}
                for col in df.columns:
                    if col.startswith("sig_"):
                        rename_map[col] = f"{team}_{col[4:]}"
                df.rename(columns=rename_map, inplace=True)
                df.rename(columns={"score": f"{team}_score"}, inplace=True)
                team_dfs[team] = df

        return team_dfs

    def _apply_ai_rescoring(
        self,
        team_dfs: dict[str, pd.DataFrame],
        all_results: list[ScreenResult],
    ) -> dict[str, pd.DataFrame]:
        """Apply Claude AI re-scoring to each team's results.

        For each team, builds ticker data from ScreenResults, checks cache,
        calls the AI client, and blends scores into the team DataFrame.
        """
        from src.core.cache import cache_json, load_cached_json

        ai_weight = self.cfg.get_nested("ai_rescore", "ai_weight", default=0.3)
        cache_ttl_h = self.cfg.get_nested("ai_rescore", "cache_ttl_hours", default=2)
        cache_ttl_s = float(cache_ttl_h) * 3600
        batch_size = self.cfg.get_nested("ai_rescore", "batch_size", default=20)

        # Group ScreenResults by team
        by_team: dict[str, list[ScreenResult]] = {}
        for r in all_results:
            by_team.setdefault(r.team, []).append(r)

        for team, df in team_dfs.items():
            team_results = by_team.get(team, [])
            if not team_results or "ticker" not in df.columns:
                continue

            # Build ticker_data dicts for the AI
            ticker_data = []
            for sr in team_results:
                ticker_data.append({
                    "ticker": sr.ticker,
                    "quant_score": sr.score,
                    "signals": sr.signals,
                    "metadata": {
                        k: v for k, v in sr.metadata.items()
                        if isinstance(v, (int, float, str, bool))
                    },
                })

            # Check cache (key = sorted tickers + team)
            tickers_key = ",".join(sorted(td["ticker"] for td in ticker_data))
            cache_key = f"{team}_{tickers_key}"
            cached = load_cached_json("ai_rescore", cache_key, ttl_seconds=cache_ttl_s)

            if cached is not None:
                logger.info("AI re-score cache hit for team [%s].", team)
                ai_results_raw = cached
            else:
                logger.info("Calling AI re-scoring for team [%s] (%d tickers)...", team, len(ticker_data))
                # Batch if needed
                all_ai: list[dict] = []
                for i in range(0, len(ticker_data), batch_size):
                    batch = ticker_data[i:i + batch_size]
                    results = self._ai_client.rescore_batch(team, batch)
                    for r in results:
                        all_ai.append({
                            "ticker": r.ticker,
                            "ai_score": r.ai_score,
                            "ai_confidence": r.ai_confidence,
                            "ai_reasoning": r.ai_reasoning,
                            "ai_flags": r.ai_flags,
                            "quant_score": r.quant_score,
                            "blended_score": r.blended_score,
                        })

                ai_results_raw = all_ai
                # Cache the results
                if ai_results_raw:
                    cache_json("ai_rescore", cache_key, ai_results_raw)

            if not ai_results_raw:
                logger.warning("No AI results for team [%s], using quant-only.", team)
                continue

            # Build lookup by ticker
            ai_lookup: dict[str, dict] = {r["ticker"]: r for r in ai_results_raw}

            # Add AI columns to the team DataFrame
            score_col = f"{team}_score"
            ai_score_col = f"{team}_ai_score"
            ai_conf_col = f"{team}_ai_confidence"
            ai_reason_col = f"{team}_ai_reasoning"
            ai_flags_col = f"{team}_ai_flags"

            ai_scores = []
            ai_confs = []
            ai_reasons = []
            ai_flags = []

            for _, row in df.iterrows():
                ticker = row.get("ticker", "")
                ai_data = ai_lookup.get(ticker)
                if ai_data:
                    ai_scores.append(ai_data["ai_score"])
                    ai_confs.append(ai_data["ai_confidence"])
                    ai_reasons.append(ai_data["ai_reasoning"])
                    ai_flags.append(", ".join(ai_data.get("ai_flags", [])))
                else:
                    ai_scores.append(float("nan"))
                    ai_confs.append("")
                    ai_reasons.append("")
                    ai_flags.append("")

            df[ai_score_col] = ai_scores
            df[ai_conf_col] = ai_confs
            df[ai_reason_col] = ai_reasons
            df[ai_flags_col] = ai_flags

            # Blend scores where AI is available (vectorized)
            if score_col in df.columns:
                has_ai = pd.notna(df[ai_score_col])
                df.loc[has_ai, score_col] = (
                    df.loc[has_ai, score_col] * (1 - ai_weight)
                    + df.loc[has_ai, ai_score_col] * ai_weight
                )

            logger.info(
                "AI re-scoring applied for team [%s]: %d/%d tickers scored.",
                team, sum(1 for s in ai_scores if not pd.isna(s)), len(df),
            )

        return team_dfs

    def _merge_and_score(self, team_dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Merge team DataFrames and compute composite score."""
        if not team_dfs:
            return pd.DataFrame()

        # Start with the first team's ticker column
        all_tickers: set[str] = set()
        for df in team_dfs.values():
            if "ticker" in df.columns:
                all_tickers.update(df["ticker"].tolist())

        if not all_tickers:
            return pd.DataFrame()

        # Create base DataFrame
        merged = pd.DataFrame({"ticker": sorted(all_tickers)})

        # Left-join each team's results
        for team, df in team_dfs.items():
            if "ticker" in df.columns:
                # Select only the score and key signal columns (avoid duplicating ticker)
                team_cols = [c for c in df.columns if c != "timestamp"]
                merged = merged.merge(
                    df[team_cols],
                    on="ticker",
                    how="left",
                    suffixes=("", f"_{team}_dup"),
                )

        # Compute composite score (weighted average of team scores)
        score_cols = [f"{t}_score" for t in self.team_weights if f"{t}_score" in merged.columns]
        if score_cols:
            for col in score_cols:
                merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)

            weights_applied = {}
            for t, w in self.team_weights.items():
                col = f"{t}_score"
                if col in merged.columns:
                    weights_applied[col] = w

            if weights_applied:
                total_weight = sum(weights_applied.values())
                merged["composite_score"] = sum(
                    merged[col] * w for col, w in weights_applied.items()
                ) / total_weight

                # Count how many teams flagged each ticker
                merged["team_count"] = sum(
                    (merged[col] > 0).astype(int) for col in score_cols
                )

                # Sort by composite score descending
                merged.sort_values("composite_score", ascending=False, inplace=True)
                merged.reset_index(drop=True, inplace=True)

        # Add metadata
        merged["scan_timestamp"] = datetime.now(timezone.utc).isoformat()

        return merged

    def save_results(
        self,
        watchlist: pd.DataFrame,
        filename: Optional[str] = None,
    ) -> Path:
        """Save watchlist to CSV in the output directory.

        Returns the path to the saved file.
        """
        output_dir = _PROJECT_ROOT / self.cfg.get_nested(
            "general", "output_dir", default="data/output",
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        if filename is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"watchlist_{ts}.csv"

        path = output_dir / filename
        watchlist.to_csv(path, index=False)
        logger.info("Watchlist saved to %s (%d rows).", path, len(watchlist))
        return path

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        """Convert a value to float, treating NaN/None as *default*."""
        if value is None:
            return default
        try:
            f = float(value)
            if pd.isna(f):
                return default
            return f
        except (ValueError, TypeError):
            return default

    def print_summary(self, watchlist: pd.DataFrame, top_n: int = 20) -> str:
        """Generate a detailed human-readable summary with per-team sub-factor scores."""
        if watchlist.empty:
            return "No results found across any team."

        active_teams = [t for t in TEAM_ORDER if t in self.screeners]
        total_teams = len(active_teams)

        lines = [
            "\u2550" * 65,
            "  妖股分析平台 \u2014 统一观察名单",
            f"  扫描时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"  活跃团队: {', '.join(active_teams)}",
            f"  标的总数: {len(watchlist)}",
            "\u2550" * 65,
        ]

        display = watchlist.head(top_n)
        for rank_num, (idx, row) in enumerate(display.iterrows(), start=1):
            ticker = row.get("ticker", "???")
            composite = self._safe_float(row.get("composite_score", 0))
            team_count = int(self._safe_float(row.get("team_count", 0)))

            lines.append("")
            lines.append(
                f"\u2501\u2501\u2501 #{rank_num} {ticker} | "
                f"综合评分: {composite:.1f}/100 | "
                f"命中团队: {team_count}/{total_teams} \u2501\u2501\u2501"
            )

            # Per-team detail -- only show active teams
            for team in active_teams:
                info = TEAM_DISPLAY[team]
                score_col = f"{team}_score"
                team_score = self._safe_float(
                    row.get(score_col) if score_col in watchlist.columns else 0
                )

                triggered = team_score > 0
                suffix = "" if triggered else "  (未触发)"

                lines.append("")
                lines.append(
                    f"  {info['icon']} {info['name']:<18s} {team_score:>5.1f}/100{suffix}"
                )

                if triggered:
                    factors = info["factors"]
                    for i, (cn_name, col_name) in enumerate(factors):
                        full_col = f"{team}_{col_name}"
                        val = self._safe_float(
                            row.get(full_col) if full_col in watchlist.columns else 0
                        )
                        connector = "\u2514\u2500" if i == len(factors) - 1 else "\u251C\u2500"
                        lines.append(f"     {connector} {cn_name}:{val:>10.1f}/25")

                    # AI re-score detail (if available)
                    ai_score_col = f"{team}_ai_score"
                    ai_conf_col = f"{team}_ai_confidence"
                    ai_reason_col = f"{team}_ai_reasoning"
                    ai_flags_col = f"{team}_ai_flags"
                    if ai_score_col in watchlist.columns:
                        ai_val = row.get(ai_score_col)
                        if pd.notna(ai_val):
                            ai_s = self._safe_float(ai_val)
                            ai_c = row.get(ai_conf_col, "")
                            ai_r = row.get(ai_reason_col, "")
                            ai_f = row.get(ai_flags_col, "")
                            lines.append(
                                f"     \U0001F916 AI\u8bc4\u5206: {ai_s:.1f}/100 "
                                f"(\u4fe1\u5fc3: {ai_c})"
                            )
                            if ai_r:
                                # Truncate long reasoning for display
                                display_reason = ai_r[:120] + "..." if len(ai_r) > 120 else ai_r
                                lines.append(f"        {display_reason}")
                            if ai_f:
                                lines.append(f"        \u6807\u8bb0: {ai_f}")

            # Composite breakdown -- only include active teams with score columns
            lines.append("")
            lines.append("  \U0001F4CA 综合评分构成:")

            parts = []
            weighted_sum = 0.0
            total_weight = 0.0
            for team in active_teams:
                info = TEAM_DISPLAY[team]
                score_col = f"{team}_score"
                if score_col not in watchlist.columns:
                    continue
                w = self.team_weights.get(team, 1.0)
                ts = self._safe_float(row.get(score_col))
                parts.append(f"{info['weight_label']}\u00D7{w}({ts:.1f})")
                weighted_sum += ts * w
                total_weight += w

            lines.append(f"     {' + '.join(parts)}")
            computed = weighted_sum / total_weight if total_weight else 0
            lines.append(
                f"     = 加权总分 {weighted_sum:.1f} \u00F7 "
                f"加权团队数 {total_weight:.1f} = 综合 {computed:.1f}"
            )

        lines.append("")
        lines.append("\u2550" * 65)
        lines.append("NOTE: Phase 1 prototype. Free-tier data with 15-min delay.")
        lines.append("      Not investment advice. Paper trading validation only.")

        summary = "\n".join(lines)
        return summary
