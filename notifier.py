"""
notifier.py – Telegram text-only alert delivery with once-per-UTC-day limit
per symbol (persisted to disk so service restarts do not duplicate alerts).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict

import requests

from config import PairConfig
from vwap_engine import VWAPResult

logger = logging.getLogger(__name__)

_TELEGRAM_SEND = "https://api.telegram.org/bot{token}/sendMessage"
_STATE_FILE = Path(__file__).parent / "sent_alerts.json"


def _require(var_name: str, friendly_label: str) -> tuple[str, bool]:
    _PLACEHOLDERS = {
        "",
        "your_bot_token_here",
        "your_chat_id_here",
    }
    value = os.getenv(var_name, "").strip()
    if value in _PLACEHOLDERS:
        logger.error(
            "⚠️  %s is not set. Open .env, fill in %s=<value>, then press Ctrl+S.",
            friendly_label,
            var_name,
        )
        return value, False
    return value, True


class Notifier:
    """Sends alert text via Telegram Bot API at most once per UTC day per pair."""

    def __init__(self) -> None:
        token, ok_t = _require("TELEGRAM_BOT_TOKEN", "Telegram Bot Token")
        chat_id, ok_c = _require("TELEGRAM_CHAT_ID", "Telegram Chat ID")

        self._tg_token: str = token
        self._tg_chat_id: str = chat_id
        self._tg_ok: bool = ok_t and ok_c

        self._sent_by_day: Dict[str, str] = self._load_state()

        if self._tg_ok:
            logger.info("✅  Telegram text alerts: READY (once per 24h / UTC day)")
        else:
            logger.warning(
                "⚠️  Telegram is not configured. Alerts will be logged to console only."
            )

    def _load_state(self) -> Dict[str, str]:
        if not _STATE_FILE.exists():
            return {}
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Could not read %s (%s) — starting fresh state.", _STATE_FILE, exc)
            return {}

    def _save_state(self) -> None:
        try:
            _STATE_FILE.write_text(json.dumps(self._sent_by_day, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to persist alert state to %s: %s", _STATE_FILE, exc)

    def maybe_alert(self, result: VWAPResult, pair: PairConfig) -> bool:
        """
        Send a Telegram alert if result.alert_triggered is True and this symbol
        has not already alerted during result.session_date (00:00 UTC day).
        """
        if not result.alert_triggered:
            return False

        if self._sent_by_day.get(result.symbol) == result.session_date:
            logger.info(
                "Alert for %s already sent for UTC session %s — skipping duplicate.",
                result.symbol,
                result.session_date,
            )
            return False

        if not self._tg_ok:
            return False

        msg = self._format_message(result, pair)
        if self._send_telegram(msg):
            self._sent_by_day[result.symbol] = result.session_date
            self._save_state()
            return True
        return False

    def send_test_message(self) -> bool:
        if not self._tg_ok:
            logger.error(
                "❌  Telegram test skipped — TELEGRAM_BOT_TOKEN or "
                "TELEGRAM_CHAT_ID is not configured in .env."
            )
            return False

        msg = (
            "🧪 *VWAP Multi-Alert — Test Message*\n\n"
            "✅ Telegram text-only delivery is active (once per UTC day per pair)."
        )
        return self._send_telegram(msg)

    @staticmethod
    def _format_message(result: VWAPResult, pair: PairConfig) -> str:
        return (
            f"⚠️ *Daily VWAP Band Gap Alert* — {pair.display_name}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 UTC Session:   `{result.session_date}`\n"
            f"📊 VWAP Mid:      `{result.vwap_mid:.4f}`\n"
            f"📈 Upper Band:    `{result.vwap_upper:.4f}`\n"
            f"📉 Lower Band:    `{result.vwap_lower:.4f}`\n"
            f"↕️ Band Gap (U-L):`{result.gap:.4f}`\n"
            f"🎯 Min Gap Req:   `{result.min_gap:.4f}`\n"
            f"💰 Last Price:    `{result.last_price:.4f}`\n"
            f"🕯 Session Bars:  {result.candle_count} × {pair.timeframe} (00:00 UTC)\n"
        )

    def _send_telegram(self, text: str) -> bool:
        url = _TELEGRAM_SEND.format(token=self._tg_token)
        payload = {
            "chat_id": self._tg_chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("✅  Telegram message delivered.")
            return True
        except requests.HTTPError as exc:
            try:
                detail = exc.response.json().get("description", str(exc))
            except Exception:
                detail = str(exc)
            logger.error("❌  Telegram delivery failed: %s", detail)
            return False
        except requests.Timeout:
            logger.error("❌  Telegram request timed out.")
            return False
        except requests.RequestException as exc:
            logger.error("❌  Telegram network error: %s", exc)
            return False