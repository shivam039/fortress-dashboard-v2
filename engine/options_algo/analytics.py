"""Deterministic, provider-neutral options chain analytics."""

from typing import Any, Dict, Optional

import pandas as pd

from options_algo.contracts import OptionChainResponse


def to_analytics_frame(response: OptionChainResponse) -> pd.DataFrame:
    """Convert canonical contracts at the sole legacy DataFrame boundary."""
    rows = []
    for contract in response.contracts:
        rows.append(
            {
                "Strike": contract.strike,
                "Type": contract.option_type,
                "LTP": contract.ltp,
                "Bid": contract.bid,
                "Ask": contract.ask,
                "Volume": contract.volume,
                "OI": contract.open_interest,
                "ChangeOI": contract.change_in_open_interest,
                "IV": contract.iv,
                "Delta": contract.delta,
                "Gamma": contract.gamma,
                "Theta": contract.theta,
                "Vega": contract.vega,
            }
        )
    return pd.DataFrame(rows)


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
    strikes = pd.to_numeric(enriched.get("Strike", pd.Series(dtype=float)), errors="coerce")
    atm = None
    if spot is not None and not strikes.dropna().empty:
        atm = float(strikes.loc[(strikes - spot).abs().idxmin()])

    def largest(option_type: str) -> Optional[Dict[str, float]]:
        if not {"Strike", "OI", "Type"}.issubset(enriched.columns):
            return None
        rows = enriched[enriched["Type"].eq(option_type)].copy()
        rows["Strike"] = pd.to_numeric(rows["Strike"], errors="coerce")
        rows["OI"] = pd.to_numeric(rows["OI"], errors="coerce")
        rows = rows.dropna(subset=["Strike", "OI"])
        if rows.empty:
            return None
        row = rows.sort_values(["OI", "Strike"], ascending=[False, True]).iloc[0]
        return {"strike": float(row["Strike"]), "oi": float(row["OI"])}

    def concentration(option_type: str) -> Optional[float]:
        rows = enriched[enriched["Type"].eq(option_type)]
        values = pd.to_numeric(rows.get("OI", pd.Series(dtype=float)), errors="coerce").dropna()
        total = values.sum()
        return round(float(values.max() / total), 4) if len(values) and total > 0 else None

    return {
        "spot": spot,
        "atm": atm,
        "oi_pcr": pcr(enriched, "OI"),
        "volume_pcr": pcr(enriched, "Volume"),
        "max_pain": max_pain(enriched),
        "largest_call_oi": largest("CE"),
        "largest_put_oi": largest("PE"),
        "call_oi_concentration": concentration("CE"),
        "put_oi_concentration": concentration("PE"),
    }
