"""
main.py – Entry point for vwap_multi_alert.

Usage
-----
  python main.py                 # start the live polling loop
  python main.py --test-call     # send a test Telegram message and exit
  python main.py --once          # run one poll cycle then exit (useful for cron)

Environment
-----------
  Copy .env.example → .env and fill in your credentials before running.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env BEFORE importing anything that reads env vars
load_dotenv(Path(__file__).parent / ".env")

from config import PAIRS, EngineConfig          # noqa: E402
from notifier import Notifier                   # noqa: E402
from vwap_engine import VWAPEngine              # noqa: E402


# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="VWAP Multi-Alert Bot")
    p.add_argument(
        "--test-call",
        action="store_true",
        help="Send a test Telegram message and exit.",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll cycle then exit.",
    )
    return p.parse_args()


# ── Core loop ──────────────────────────────────────────────────────────────────

def poll_once(engine: VWAPEngine, notifier: Notifier) -> None:
    """Evaluate all pairs and dispatch alerts for triggered ones."""
    for symbol, pair in PAIRS.items():
        logger.info("Checking %s …", symbol)
        result = engine.compute(pair)
        if result is None:
            logger.warning("Skipping %s — engine returned no result.", symbol)
            continue

        logger.info(
            "%s | gap=%.4f (threshold=%.4f) | alert=%s",
            symbol, result.gap, pair.min_gap, result.alert_triggered,
        )
        if result.alert_triggered:
            sent = notifier.maybe_alert(result, pair)
            if not sent:
                logger.info("Alert for %s suppressed by cooldown.", symbol)


def run_loop(engine: VWAPEngine, notifier: Notifier) -> None:
    logger.info(
        "Starting poll loop — %d pair(s), interval=%ds",
        len(PAIRS),
        EngineConfig.POLL_INTERVAL_SECONDS,
    )
    while True:
        try:
            poll_once(engine, notifier)
        except KeyboardInterrupt:
            logger.info("Interrupted by user — shutting down.")
            break
        except Exception as exc:                       # keep loop alive on error
            logger.exception("Unhandled error in poll cycle: %s", exc)

        logger.info("Sleeping %ds …", EngineConfig.POLL_INTERVAL_SECONDS)
        time.sleep(EngineConfig.POLL_INTERVAL_SECONDS)


# ── Entrypoint ─────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    notifier = Notifier()

    if args.test_call:
        logger.info("--test-call flag detected — sending test Telegram message.")
        ok = notifier.send_test_message()
        sys.exit(0 if ok else 1)

    engine = VWAPEngine()

    if args.once:
        logger.info("--once flag detected — running single poll cycle.")
        poll_once(engine, notifier)
        sys.exit(0)

    run_loop(engine, notifier)


if __name__ == "__main__":
    main()
