from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List


@dataclass
class WallLevel:
    strike: float
    oi: int
    distance_pct: float
    strength: float


@dataclass
class RegimeResult:
    classification: str
    confidence: float
    pin_probability: float
    vol_risk: str


class QuantEngine:
    """Lightweight quantitative engine used by the Tab 8 UI.

    This implementation is intentionally minimal so the app runs even when
    the full institutional modules are not present.
    """

    def calculate_gex(self, contracts: Iterable[Dict], current_price: float) -> Dict[str, float]:
        call_gex = 0.0
        put_gex = 0.0
        for contract in contracts:
            try:
                strike = float(contract.get("strike", 0) or 0)
                oi = int(contract.get("open_interest", 0) or 0)
                opt_type = (contract.get("option_type") or contract.get("type") or "").lower()
                greeks = contract.get("greeks") or {}
                gamma = float(greeks.get("gamma", 0) or contract.get("gamma", 0) or 0)
                gex = gamma * oi * 100 * float(current_price or 0)
                if opt_type == "put":
                    put_gex += gex
                else:
                    call_gex += gex
            except Exception:
                continue
        gex_index = call_gex - put_gex
        total_gex = abs(call_gex) + abs(put_gex)
        return {
            "gex_index": gex_index,
            "call_gex": call_gex,
            "put_gex": put_gex,
            "total_gex": total_gex,
        }

    def _max_oi_wall(self, contracts: List[Dict], option_type: str, current_price: float) -> WallLevel:
        filtered = [
            c for c in contracts
            if (c.get("option_type") or c.get("type") or "").lower() == option_type
        ]
        if not filtered:
            return WallLevel(strike=current_price, oi=0, distance_pct=0.0, strength=0.0)
        max_contract = max(filtered, key=lambda c: int(c.get("open_interest", 0) or 0))
        strike = float(max_contract.get("strike", current_price) or current_price)
        oi = int(max_contract.get("open_interest", 0) or 0)
        distance_pct = abs(strike - current_price) / current_price if current_price else 0.0
        strength = oi / max(oi, 1)
        return WallLevel(strike=strike, oi=oi, distance_pct=distance_pct, strength=strength)

    def detect_walls(self, contracts: List[Dict], current_price: float, expiration: str) -> tuple[WallLevel, WallLevel]:
        call_wall = self._max_oi_wall(contracts, "call", current_price)
        put_wall = self._max_oi_wall(contracts, "put", current_price)
        return call_wall, put_wall

    def classify_regime(self, contracts: List[Dict], current_price: float, gamma_neta: float) -> RegimeResult:
        abs_gamma = abs(gamma_neta)
        if abs_gamma < 1e7:
            classification = "CHOP"
            confidence = 0.55
            pin_probability = 0.6
        else:
            classification = "TREND"
            confidence = 0.7
            pin_probability = 0.35
        vol_risk = "LOW" if abs_gamma < 5e7 else "ELEVATED"
        return RegimeResult(
            classification=classification,
            confidence=confidence,
            pin_probability=pin_probability,
            vol_risk=vol_risk,
        )

    def calculate_targets(self, call_wall: WallLevel, put_wall: WallLevel, current_price: float, atr: float) -> Dict[str, Dict[str, float | str]]:
        atr = float(atr or 0)
        return {
            "MEAN_REVERT": {
                "target": (call_wall.strike + put_wall.strike) / 2 if call_wall and put_wall else current_price,
                "probability": 0.45,
                "type": "pin",
                "invalidation": current_price - atr,
            },
            "BREAKOUT_UP": {
                "target": max(call_wall.strike, current_price + atr),
                "probability": 0.3,
                "type": "trend",
                "invalidation": current_price - atr,
            },
            "BREAKOUT_DOWN": {
                "target": min(put_wall.strike, current_price - atr),
                "probability": 0.25,
                "type": "trend",
                "invalidation": current_price + atr,
            },
        }
