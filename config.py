from dataclasses import dataclass
from typing import Dict


@dataclass
class PairConfig:
    symbol: str
    min_gap: float
    timeframe: str = "15m"
    window: int = 96
    cooldown_seconds: int = 86400
    display_name: str = ""

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.symbol


PAIRS: Dict[str, PairConfig] = {
    "XAUT/USDT": PairConfig(
        symbol="XAUT/USDT",
        display_name="Gold Proxy (XAUT/USDT)",
        min_gap=140.0,
        cooldown_seconds=86400,
    ),
}


class EngineConfig:
    POLL_INTERVAL_SECONDS: int = 60
    EXCHANGE_ID: str = "binance"
    USE_SANDBOX: bool = False