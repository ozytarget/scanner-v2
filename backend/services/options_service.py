"""Options analytics: Max Pain, GEX, Put/Call ratios, etc."""
import numpy as np
from typing import Optional
from backend.services.tradier import get_expirations, get_option_chain, get_quote


def compute_max_pain(options: list[dict]) -> Optional[float]:
    """Compute the max pain strike from an options chain."""
    if not options:
        return None

    # Collect unique strikes
    strikes = sorted({float(o["strike"]) for o in options if o.get("strike")})
    if not strikes:
        return None

    best_strike = None
    min_pain = float("inf")

    for test_strike in strikes:
        pain = 0.0
        for o in options:
            otype = o.get("option_type", "")
            strike = float(o.get("strike", 0))
            oi = float(o.get("open_interest", 0) or 0)
            if otype == "call":
                intrinsic = max(0.0, test_strike - strike)
            elif otype == "put":
                intrinsic = max(0.0, strike - test_strike)
            else:
                continue
            pain += intrinsic * oi

        if pain < min_pain:
            min_pain = pain
            best_strike = test_strike

    return best_strike


def compute_gex(options: list[dict], spot: float) -> dict:
    """
    Compute Gamma Exposure (GEX) per strike and net GEX.
    Returns: {strike: net_gex, ..., 'total': float}
    """
    from scipy.stats import norm
    from math import log, sqrt, exp

    def black_scholes_gamma(S, K, T, r, sigma):
        if T <= 0 or sigma <= 0:
            return 0.0
        d1 = (log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt(T))
        return norm.pdf(d1) / (S * sigma * sqrt(T))

    r = 0.05  # risk-free rate proxy
    result = {}
    total_gex = 0.0

    for o in options:
        try:
            strike = float(o.get("strike", 0))
            oi = float(o.get("open_interest", 0) or 0)
            iv = float(o.get("greeks", {}).get("mid_iv", 0) or 0)
            dte = float(o.get("expiration_date", "") and _dte(o["expiration_date"]))
            otype = o.get("option_type", "")

            if strike <= 0 or oi <= 0 or iv <= 0 or dte < 0:
                continue

            T = dte / 365
            gamma = black_scholes_gamma(spot, strike, T, r, iv)
            gex = gamma * oi * spot * 100  # contract multiplier

            if otype == "put":
                gex = -gex  # puts create negative GEX

            result[strike] = result.get(strike, 0.0) + gex
            total_gex += gex
        except (ValueError, TypeError, ZeroDivisionError):
            continue

    result["total"] = total_gex
    return result


def compute_put_call_ratio(options: list[dict]) -> dict:
    call_oi = sum(float(o.get("open_interest", 0) or 0) for o in options if o.get("option_type") == "call")
    put_oi = sum(float(o.get("open_interest", 0) or 0) for o in options if o.get("option_type") == "put")
    call_vol = sum(float(o.get("volume", 0) or 0) for o in options if o.get("option_type") == "call")
    put_vol = sum(float(o.get("volume", 0) or 0) for o in options if o.get("option_type") == "put")

    return {
        "call_oi": call_oi,
        "put_oi": put_oi,
        "oi_pcr": round(put_oi / call_oi, 4) if call_oi else None,
        "call_volume": call_vol,
        "put_volume": put_vol,
        "volume_pcr": round(put_vol / call_vol, 4) if call_vol else None,
    }


def _dte(exp_str: str) -> float:
    """Days to expiration from YYYY-MM-DD string."""
    from datetime import date
    exp = date.fromisoformat(exp_str)
    return max(0, (exp - date.today()).days)


async def get_full_analysis(ticker: str, expiration: str) -> dict:
    """Single endpoint: returns max pain, GEX, PCR for a ticker+expiration."""
    options = await get_option_chain(ticker, expiration)
    quote = await get_quote(ticker)
    spot = float(quote.get("last", 0) or 0)

    max_pain = compute_max_pain(options)
    gex = compute_gex(options, spot) if spot else {}
    pcr = compute_put_call_ratio(options)

    # Build strike-level OI arrays for charting
    calls = sorted([o for o in options if o.get("option_type") == "call"], key=lambda x: float(x.get("strike", 0)))
    puts = sorted([o for o in options if o.get("option_type") == "put"], key=lambda x: float(x.get("strike", 0)))

    strike_labels = sorted({float(o.get("strike", 0)) for o in options if o.get("strike")})

    call_oi_map = {float(o["strike"]): float(o.get("open_interest", 0) or 0) for o in calls}
    put_oi_map = {float(o["strike"]): float(o.get("open_interest", 0) or 0) for o in puts}

    return {
        "ticker": ticker,
        "expiration": expiration,
        "spot": spot,
        "max_pain": max_pain,
        "gex": gex,
        "pcr": pcr,
        "strikes": strike_labels,
        "call_oi": [call_oi_map.get(s, 0) for s in strike_labels],
        "put_oi": [put_oi_map.get(s, 0) for s in strike_labels],
    }
