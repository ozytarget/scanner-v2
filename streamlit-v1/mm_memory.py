from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class TickerProfile:
    pin_hit_rate: float = 0.48
    wall_respect_rate: float = 0.52
    vol_expansion_freq: float = 0.31
    sample_size: int = 120
    confidence: float = 0.58


class MemorySystem:
    """Minimal memory system placeholder for Tab 8.

    Stores no persistent state; returns conservative defaults.
    """

    def get_ticker_profile(self, ticker: str) -> Dict[str, float | int]:
        profile = TickerProfile()
        return {
            "pin_hit_rate": profile.pin_hit_rate,
            "wall_respect_rate": profile.wall_respect_rate,
            "vol_expansion_freq": profile.vol_expansion_freq,
            "sample_size": profile.sample_size,
            "confidence": profile.confidence,
        }

    def get_backtesting_summary(self, ticker: str, days: int = 30) -> Dict[str, float | int]:
        return {
            "total_outcomes": max(days, 1),
            "hit_rate": 52.0,
            "avg_price_move": 1.6,
        }
