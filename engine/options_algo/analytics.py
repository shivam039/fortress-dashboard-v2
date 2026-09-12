"""Deterministic, provider-neutral options chain analytics."""

from typing import Any, Dict, Optional

import pandas as pd


def add_moneyness(chain: pd.DataFrame, spot: Optional[float]) -> pd.DataFrame:
    result = chain.copy()
    result["Moneyness"] = "UNAVAILABLE"
    if spot is None or spot <= 0 or result.empty:
        return result
    strikes = pd.to_numeric(result["Strike"], errors="coerce")
    distance = (strikes - spot).abs()
    if distance.notna().any():
        atm_distance = distance.min()
        atm = distance.eq(atm_distance)
        calls = result["Type"].eq("CE")
        result.loc[atm, "Moneyness"] = "ATM"
        result.loc[calls & ~atm & strikes.lt(spot), "Moneyness"] = "ITM"
        result.loc[calls & ~atm & strikes.gt(spot), "Moneyness"] = "OTM"
        result.loc[~calls & ~atm & strikes.gt(spot), "Moneyness"] = "ITM"
        result.loc[~calls & ~atm & strikes.lt(spot), "Moneyness"] = "OTM"
    return result


def pcr(chain: pd.DataFrame, field: str) -> Optional[float]:
    if field not in chain.columns:
        return None
    values = pd.to_numeric(chain[field], errors="coerce")
    calls = values[chain["Type"].eq("CE")].sum(min_count=1)
    puts = values[chain["Type"].eq("PE")].sum(min_count=1)
    if pd.isna(calls) or pd.isna(puts) or calls == 0:
        return None
    return round(float(puts / calls), 4)


def max_pain(chain: pd.DataFrame) -> Optional[float]:
    required = {"Strike", "Type", "OI"}
    if chain.empty or not required.issubset(chain.columns):
        return None
    rows = chain[["Strike", "Type", "OI"]].copy()
    rows["Strike"] = pd.to_numeric(rows["Strike"], errors="coerce")
    rows["OI"] = pd.to_numeric(rows["OI"], errors="coerce")
    if rows.isna().any().any() or (rows["OI"] < 0).any():
        return None
    strikes = sorted(rows["Strike"].unique())
    if not strikes or not {"CE", "PE"}.issubset(set(rows["Type"])):
        return None
    call_oi = rows[rows["Type"].eq("CE")].groupby("Strike")["OI"].sum()
    put_oi = rows[rows["Type"].eq("PE")].groupby("Strike")["OI"].sum()
    if set(call_oi.index) != set(strikes) or set(put_oi.index) != set(strikes):
        return None
    losses: Dict[float, float] = {}
    for expiry_strike in strikes:
        call_loss = sum(
            max(expiry_strike - strike, 0) * call_oi[strike]
            for strike in strikes
        )
        put_loss = sum(
            max(strike - expiry_strike, 0) * put_oi[strike]
            for strike in strikes
        )
        losses[expiry_strike] = call_loss + put_loss
    return min(losses, key=lambda strike: (losses[strike], strike))


def summarize(chain: pd.DataFrame, spot: Optional[float]) -> Dict[str, Any]:
    enriched = add_moneyness(chain, spot)
    return {
        "spot": spot,
        "oi_pcr": pcr(enriched, "OI"),
        "volume_pcr": pcr(enriched, "Volume"),
        "max_pain": max_pain(enriched),
    }
