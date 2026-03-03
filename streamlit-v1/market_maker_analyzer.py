from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Dict, List, Optional, Tuple

import requests


@dataclass
class LevelInfo:
    level: float
    probability: float


@dataclass
class ScenarioInfo:
    label: str
    bull_prob: float
    bear_prob: float


class MarketMakerAnalyzer:
    def __init__(
        self,
        tradier_key: str,
        fmp_key: str,
        tradier_base_url: str,
        fmp_base_url: str,
    ) -> None:
        self.tradier_key = tradier_key
        self.fmp_key = fmp_key
        self.tradier_base_url = tradier_base_url.rstrip("/")
        self.fmp_base_url = fmp_base_url.rstrip("/")

    def _tradier_get(self, path: str, params: Dict[str, str]) -> Dict:
        url = f"{self.tradier_base_url}{path}"
        headers = {"Authorization": f"Bearer {self.tradier_key}", "Accept": "application/json"}
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def get_option_expirations(self, symbol: str) -> List[str]:
        data = self._tradier_get("/markets/options/expirations", {"symbol": symbol})
        expirations = data.get("expirations", {}).get("date", [])
        if isinstance(expirations, str):
            return [expirations]
        return expirations

    def get_option_chain(self, symbol: str, expiration: str) -> List[Dict]:
        data = self._tradier_get(
            "/markets/options/chains",
            {"symbol": symbol, "expiration": expiration, "greeks": "true"},
        )
        options = data.get("options", {}).get("option", [])
        if isinstance(options, dict):
            return [options]
        return options

    def get_quote(self, symbol: str) -> Dict:
        data = self._tradier_get("/markets/quotes", {"symbols": symbol})
        quote = data.get("quotes", {}).get("quote", {})
        return quote or {}

    def _normalize_iv(self, iv_value: Optional[float]) -> float:
        if iv_value is None:
            return 0.0
        iv = float(iv_value)
        if iv > 3:
            iv = iv / 100.0
        return max(iv, 0.0)

    def _aggregate_by_strike(self, options: List[Dict], price: float) -> Dict[float, Dict]:
        aggregates: Dict[float, Dict] = {}
        for option in options:
            strike = float(option.get("strike") or 0)
            if strike <= 0:
                continue
            opt_type = option.get("option_type") or option.get("type") or ""
            greeks = option.get("greeks") or {}
            gamma = float(greeks.get("gamma") or 0.0)
            oi = float(option.get("open_interest") or 0.0)
            volume = float(option.get("volume") or 0.0)
            iv = self._normalize_iv(
                option.get("implied_volatility")
                or greeks.get("mid_iv")
                or greeks.get("smv_vol")
            )

            gamma_exposure = gamma * oi * 100.0 * price

            if strike not in aggregates:
                aggregates[strike] = {
                    "call_gamma": 0.0,
                    "put_gamma": 0.0,
                    "call_volume": 0.0,
                    "put_volume": 0.0,
                    "call_oi": 0.0,
                    "put_oi": 0.0,
                    "iv_weight": 0.0,
                    "iv_oi": 0.0,
                }

            target = aggregates[strike]
            if opt_type.lower().startswith("c"):
                target["call_gamma"] += gamma_exposure
                target["call_volume"] += volume
                target["call_oi"] += oi
            else:
                target["put_gamma"] += gamma_exposure
                target["put_volume"] += volume
                target["put_oi"] += oi

            if oi > 0 and iv > 0:
                target["iv_weight"] += iv * oi
                target["iv_oi"] += oi

        return aggregates

    def _weighted_iv(self, aggregates: Dict[float, Dict]) -> float:
        total_iv_weight = 0.0
        total_oi = 0.0
        for data in aggregates.values():
            total_iv_weight += data["iv_weight"]
            total_oi += data["iv_oi"]
        if total_oi <= 0:
            return 0.0
        return total_iv_weight / total_oi

    def _target_from_aggregates(
        self,
        aggregates: Dict[float, Dict],
        price: float,
        iv: float,
        days: int,
    ) -> float:
        total_weight = 0.0
        weighted_sum = 0.0
        dominant_strike = 0.0
        dominant_weight = 0.0
        net_gamma_total = 0.0
        for strike, data in aggregates.items():
            net = data["call_gamma"] - data["put_gamma"]
            weight = abs(net)
            net_gamma_total += net
            if weight == 0:
                continue
            weighted_sum += strike * weight
            total_weight += weight
            if weight > dominant_weight:
                dominant_weight = weight
                dominant_strike = strike

        if total_weight == 0:
            return 0.0

        center_mass = weighted_sum / total_weight
        if dominant_strike == 0.0:
            dominant_strike = center_mass

        blended = center_mass * 0.6 + dominant_strike * 0.4

        if price > 0 and iv > 0 and days > 0:
            t = days / 365.0
            sigma_move = price * iv * math.sqrt(t)
            drift = max(-1.0, min(1.0, net_gamma_total / (abs(net_gamma_total) + 1e-6)))
            blended += sigma_move * 0.25 * drift

        return blended

    def _pivot_from_aggregates(self, aggregates: Dict[float, Dict]) -> float:
        strikes = sorted(aggregates.keys())
        if not strikes:
            return 0.0
        net_by_strike = []
        for strike in strikes:
            data = aggregates[strike]
            net = data["call_gamma"] - data["put_gamma"]
            net_by_strike.append((strike, net))
        for idx in range(1, len(net_by_strike)):
            prev_strike, prev_net = net_by_strike[idx - 1]
            strike, net = net_by_strike[idx]
            if prev_net == 0:
                return prev_strike
            if (prev_net < 0 and net > 0) or (prev_net > 0 and net < 0):
                span = strike - prev_strike
                if span == 0:
                    return strike
                ratio = abs(prev_net) / (abs(prev_net) + abs(net))
                return prev_strike + span * ratio
        closest = min(net_by_strike, key=lambda item: abs(item[1]))
        return closest[0]

    def _normal_cdf(self, x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def _level_probability(self, price: float, level: float, iv: float, days: int) -> float:
        if price <= 0 or level <= 0 or iv <= 0 or days <= 0:
            return 50.0
        t = days / 365.0
        sigma = iv * math.sqrt(t)
        if sigma == 0:
            return 50.0
        z = math.log(level / price) / sigma
        if level >= price:
            prob = 1.0 - self._normal_cdf(z)
        else:
            prob = self._normal_cdf(z)
        return max(1.0, min(99.0, prob * 100.0))

    def _scenario_from_stats(
        self,
        call_gamma: float,
        put_gamma: float,
        call_volume: float,
        put_volume: float,
        price: float,
        pivot: float,
    ) -> ScenarioInfo:
        def ratio_score(a: float, b: float) -> float:
            if a <= 0 and b <= 0:
                return 0.0
            return (a - b) / (abs(a) + abs(b) + 1e-6)

        gamma_score = ratio_score(call_gamma, put_gamma)
        volume_score = ratio_score(call_volume, put_volume)
        if pivot > 0:
            price_score = max(-1.0, min(1.0, (price - pivot) / pivot))
        else:
            price_score = 0.0

        combined = (gamma_score + volume_score + price_score) / 3.0
        bull_prob = max(1.0, min(99.0, (combined + 1.0) / 2.0 * 100.0))
        bear_prob = 100.0 - bull_prob
        if bull_prob > 55.0:
            label = "BULLISH"
        elif bull_prob < 45.0:
            label = "BEARISH"
        else:
            label = "NEUTRAL"
        return ScenarioInfo(label=label, bull_prob=round(bull_prob, 1), bear_prob=round(bear_prob, 1))

    def _pick_levels(
        self,
        aggregates: Dict[float, Dict],
        price: float,
        iv: float,
        days: int,
    ) -> Tuple[List[LevelInfo], List[LevelInfo]]:
        above = []
        below = []
        for strike, data in aggregates.items():
            net = data["call_gamma"] - data["put_gamma"]
            magnitude = abs(net)
            if strike >= price:
                above.append((strike, magnitude))
            else:
                below.append((strike, magnitude))
        above.sort(key=lambda item: item[1], reverse=True)
        below.sort(key=lambda item: item[1], reverse=True)

        resistances = []
        supports = []
        for strike, _ in above[:2]:
            prob = self._level_probability(price, strike, iv, days)
            resistances.append(LevelInfo(level=strike, probability=round(prob, 1)))
        for strike, _ in below[:2]:
            prob = self._level_probability(price, strike, iv, days)
            supports.append(LevelInfo(level=strike, probability=round(prob, 1)))
        return resistances, supports

    def analyze_chain(self, symbol: str, expiration: Optional[str] = None) -> Dict:
        quote = self.get_quote(symbol)
        price = float(quote.get("last") or quote.get("close") or quote.get("bid") or 0.0)
        expirations_all = sorted(self.get_option_expirations(symbol))
        expirations = expirations_all
        if expiration:
            expirations = [exp for exp in expirations_all if exp == expiration]

        timeline_expirations = []
        timeline_total = []
        timeline_call = []
        timeline_put = []
        timeline_hist = []
        timeline_target = []
        expiration_stats = []
        per_expiration_sentiment = {}

        all_options: List[Dict] = []
        for exp in expirations:
            options = self.get_option_chain(symbol, exp)
            if not options:
                continue
            aggregates = self._aggregate_by_strike(options, price)
            iv_exp = self._weighted_iv(aggregates)
            try:
                days_exp = max(1, abs((datetime.fromisoformat(exp) - datetime.now(timezone.utc).replace(tzinfo=None)).days))
            except ValueError:
                days_exp = 7
            pivot_exp = self._pivot_from_aggregates(aggregates)
            resistances_exp, supports_exp = self._pick_levels(aggregates, price, iv_exp, days_exp)
            call_gamma = sum(item["call_gamma"] for item in aggregates.values())
            put_gamma = sum(item["put_gamma"] for item in aggregates.values())
            total_gamma = call_gamma - put_gamma

            target_price = self._target_from_aggregates(aggregates, price, iv_exp, days_exp)

            call_oi = sum(item["call_oi"] for item in aggregates.values())
            put_oi = sum(item["put_oi"] for item in aggregates.values())
            total_oi = call_oi + put_oi
            put_call = (put_oi / call_oi) if call_oi > 0 else 0.0

            call_volume = sum(item["call_volume"] for item in aggregates.values())
            put_volume = sum(item["put_volume"] for item in aggregates.values())
            dominance = 0.0
            if call_volume + put_volume > 0:
                dominance = (call_volume - put_volume) / (call_volume + put_volume)

            per_expiration_sentiment[exp] = {
                "dominance": round(dominance, 3),
                "label": "CALLS" if dominance > 0 else "PUTS" if dominance < 0 else "NEUTRAL",
                "call_volume": round(call_volume, 2),
                "put_volume": round(put_volume, 2),
            }

            timeline_expirations.append(exp)
            timeline_total.append(round(total_gamma, 2))
            timeline_call.append(round(call_gamma, 2))
            timeline_put.append(round(put_gamma, 2))
            timeline_hist.append(0.0)
            timeline_target.append(round(target_price, 2) if target_price else None)
            expiration_stats.append(
                {
                    "expiration": exp,
                    "pivot": round(pivot_exp, 2) if pivot_exp else None,
                    "total_oi": int(total_oi),
                    "call_oi": int(call_oi),
                    "put_oi": int(put_oi),
                    "put_call": round(put_call, 2),
                    "resistance": [level.__dict__ for level in resistances_exp],
                    "support": [level.__dict__ for level in supports_exp],
                }
            )
            all_options.extend(options)

        if not all_options:
            return {
                "symbol": symbol,
                "price": price,
                "available_expirations": expirations_all,
                "gamma_timeline": {
                    "expirations": timeline_expirations,
                    "total": timeline_total,
                    "call": timeline_call,
                    "put": timeline_put,
                    "historical": timeline_hist,
                    "target": timeline_target,
                },
                "expiration_stats": expiration_stats,
                "scenario": None,
                "pivot": None,
                "levels": {"resistance": [], "support": []},
                "sentiment_by_expiration": per_expiration_sentiment,
                "price_header": {
                    "historical": price,
                    "current": price,
                    "projected": price,
                    "momentum": 0,
                },
            }

        aggregates_all = self._aggregate_by_strike(all_options, price)
        pivot = self._pivot_from_aggregates(aggregates_all)
        iv = self._weighted_iv(aggregates_all)

        days = 7
        if expirations:
            try:
                nearest = min(expirations, key=lambda d: abs((datetime.fromisoformat(d) - datetime.now(timezone.utc).replace(tzinfo=None)).days))
                days = max(1, abs((datetime.fromisoformat(nearest) - datetime.now(timezone.utc).replace(tzinfo=None)).days))
            except ValueError:
                days = 7

        resistances, supports = self._pick_levels(aggregates_all, price, iv, days)

        call_gamma_total = sum(item["call_gamma"] for item in aggregates_all.values())
        put_gamma_total = sum(item["put_gamma"] for item in aggregates_all.values())
        call_volume_total = sum(item["call_volume"] for item in aggregates_all.values())
        put_volume_total = sum(item["put_volume"] for item in aggregates_all.values())

        scenario = self._scenario_from_stats(
            call_gamma_total,
            put_gamma_total,
            call_volume_total,
            put_volume_total,
            price,
            pivot,
        )

        return {
            "symbol": symbol,
            "price": round(price, 2),
            "available_expirations": expirations_all,
            "gamma_timeline": {
                "expirations": timeline_expirations,
                "total": timeline_total,
                "call": timeline_call,
                "put": timeline_put,
                "historical": timeline_hist,
                "target": timeline_target,
            },
            "expiration_stats": expiration_stats,
            "scenario": {
                "label": scenario.label,
                "bull_prob": scenario.bull_prob,
                "bear_prob": scenario.bear_prob,
            },
            "pivot": round(pivot, 2),
            "levels": {
                "resistance": [level.__dict__ for level in resistances],
                "support": [level.__dict__ for level in supports],
            },
            "sentiment_by_expiration": per_expiration_sentiment,
            "price_header": {
                "historical": round(price, 2),
                "current": round(price, 2),
                "projected": round(price, 2),
                "momentum": 0,
            },
        }
