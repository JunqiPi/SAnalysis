#!/usr/bin/env python3
"""
SAnalysis - Meme Stock Analysis Platform
Phase 1: Zero-Cost Prototype

Usage:
    # Run all teams
    python main.py

    # Run specific teams
    python main.py --teams red green

    # Analyze specific tickers across all teams
    python main.py --tickers GME AMC TSLA

    # Run sequentially (for debugging)
    python main.py --no-parallel

    # Show top N results
    python main.py --top 30

    # Clear cache and re-scan
    python main.py --clear-cache
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

__version__ = "0.3.0"

from src.pipeline.orchestrator import PipelineOrchestrator


def setup_logging(level: str = "INFO") -> None:
    """Configure logging with a clean format."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy third-party loggers
    for noisy in ("urllib3", "yfinance", "peewee", "requests", "chardet"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SAnalysis - Meme Stock Five-Team Screening Platform",
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"SAnalysis v{__version__}",
    )
    parser.add_argument(
        "--teams",
        nargs="+",
        choices=["red", "orange", "yellow", "green", "blue"],
        default=None,
        help="Which teams to run (default: all)",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Specific tickers to analyze (overrides team candidate discovery)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of top results to display (default: 20)",
    )
    parser.add_argument(
        "--no-parallel",
        action="store_true",
        help="Run teams sequentially instead of in parallel",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save results to CSV",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear all cached data before running",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging verbosity",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.log_level)

    logger = logging.getLogger("main")
    logger.info("SAnalysis v%s - Starting scan...", __version__)

    # Clear cache if requested
    if args.clear_cache:
        from src.core.cache import clear_cache
        clear_cache()

    t0 = time.monotonic()

    orchestrator = PipelineOrchestrator(teams=args.teams)
    watchlist = orchestrator.run(
        tickers=args.tickers,
        parallel=not args.no_parallel,
    )

    elapsed = time.monotonic() - t0

    if watchlist.empty:
        logger.warning("Scan completed with no results.")
        print("\nNo results found. Check logs for errors.")
        return 1

    # Print summary
    summary = orchestrator.print_summary(watchlist, top_n=args.top)
    print(summary)

    # Save to CSV
    if not args.no_save:
        path = orchestrator.save_results(watchlist)
        print(f"\nResults saved to: {path}")

    logger.info(
        "Scan complete. %d tickers in watchlist (%.1fs total).",
        len(watchlist), elapsed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
