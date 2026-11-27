"""
vwap_engine.py – Fetches OHLCV candles via ccxt for the 00:00 UTC session
and computes session high/low range (without multiplier bands).

Alert condition (Daily 00:00 UTC session)
-----------------------------------------
  gap = session_high - session_low
  Alert fires when gap >= pair.min_gap.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import ccxt
import numpy as np

from config import EngineConfig, PairConfig

logger = logging.getLogger(__name__)


@dataclass
class VWAPResult:
    symbol: str
    session_date: str     # YYYY-MM-DD (UTC)
    vwap_mid: float
    vwap_upper: float     # session high (upper)
    vwap_lower: float     # session low (bottom)
    gap: float            # session_high - session_low
    last_price: float
    candle_count: int
    alert_triggered: bool
    min_gap: float


class VWAPEngine:
    """Thin wrapper around ccxt that computes daily 00:00 UTC session metrics."""

    def __init__(self) -> None:
        exchange_class = getattr(ccxt, EngineConfig.EXCHANGE_ID)
        self._exchange: ccxt.Exchange = exchange_class(
            {
                "apiKey": os.getenv("BINANCE_API_KEY", ""),
                "secret": os.getenv("BINANCE_API_SECRET", ""),
                "enableRateLimit": True,
            }
        )
        if EngineConfig.USE_SANDBOX:
            self._exchange.set_sandbox_mode(True)
        logger.info("VWAPEngine initialised on %s (Daily 00:00 UTC session, no multiplier)", EngineConfig.EXCHANGE_ID)

    @staticmethod
    def _utc_day_start_ms(now_utc: Optional[datetime] = None) -> int:
        """Return 00:00:00 UTC of the given (or current) UTC date in milliseconds."""
        dt = now_utc or datetime.now(timezone.utc)
        midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(midnight.timestamp() * 1000)

    def compute(self, pair: PairConfig) -> Optional[VWAPResult]:
        """
        Fetch today's 00:00 UTC session candles for *pair* and return a VWAPResult.
        Returns None on any fetch or computation error.
        """
        now_utc = datetime.now(timezone.utc)
        session_date = now_utc.strftime("%Y-%m-%d")
        session_start_ms = self._utc_day_start_ms(now_utc)
        fetch_limit = max(pair.window, 500)

        try:
            ohlcv = self._exchange.fetch_ohlcv(
                pair.symbol,
                timeframe=pair.timeframe,
                since=session_start_ms,
                limit=fetch_limit,
            )
        except ccxt.BaseError as exc:
            logger.error("ccxt error fetching %s: %s", pair.symbol, exc)
            return None

        if not ohlcv:
            logger.warning("No candles returned for %s since 00:00 UTC", pair.symbol)
            return None

        session_candles = [row for row in ohlcv if row[0] >= session_start_ms]
        if not session_candles:
            logger.info("No session candles yet at 00:00 UTC for %s", pair.symbol)
            return None

        return self._calculate(pair, session_candles, session_date)

    @staticmethod
    def _calculate(pair: PairConfig, ohlcv: list, session_date: str) -> VWAPResult:
        """Pure computation over current daily session candles — no I/O."""
        arr = np.array(ohlcv, dtype=float)
        highs   = arr[:, 2]
        lows    = arr[:, 3]
        closes  = arr[:, 4]
        volumes = arr[:, 5]

        tp = (highs + lows + closes) / 3.0
        total_vol = float(volumes.sum())
        vwap_mid = float(np.dot(tp, volumes) / total_vol) if total_vol > 0.0 else float(tp.mean())

        session_high = float(highs.max())
        session_low = float(lows.min())
        last_price = float(closes[-1])

        gap = session_high - session_low
        alert = gap >= pair.min_gap

        return VWAPResult(
            symbol=pair.symbol,
            session_date=session_date,
            vwap_mid=vwap_mid,
            vwap_upper=session_high,
            vwap_lower=session_low,
            gap=gap,
            last_price=last_price,
            candle_count=len(ohlcv),
            alert_triggered=alert,
            min_gap=pair.min_gap,
        )