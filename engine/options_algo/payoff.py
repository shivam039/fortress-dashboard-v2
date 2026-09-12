"""Pure, non-executing payoff calculations for the Options Strategy Lab."""

from dataclasses import dataclass
from typing import List, Optional, Sequence


@dataclass(frozen=True)
class StrategyLeg:
    """One option leg; quantity is positive and side controls its sign."""

    option_type: str
    strike: float
    premium: float
    quantity: int = 1
    side: str = "BUY"


def _leg_payoff(leg: StrategyLeg, price: float) -> float:
    intrinsic = max(price - leg.strike, 0.0) if leg.option_type == "CE" else max(leg.strike - price, 0.0)
    sign = 1.0 if leg.side == "BUY" else -1.0
    return sign * (intrinsic - leg.premium) * leg.quantity


def payoff(legs: Sequence[StrategyLeg], underlying_prices: Sequence[float]) -> List[float]:
    """Return expiry P/L for each price; never places or simulates an order."""
    if not legs:
        return [0.0 for _ in underlying_prices]
    return [round(sum(_leg_payoff(leg, price) for leg in legs), 8) for price in underlying_prices]


def summary(legs: Sequence[StrategyLeg], price_floor: float = 0.0, price_ceiling: Optional[float] = None) -> dict:
    """Calculate bounded risk metrics from payoff breakpoints.

    ``None`` means the metric is not finite or cannot be established from the
    supplied range; it is never represented as zero.
    """
    if not legs:
        return {"max_profit": None, "max_loss": None, "breakevens": []}
    ceiling = price_ceiling or max(leg.strike for leg in legs) * 2.0
    points = sorted({price_floor, ceiling, *(leg.strike for leg in legs)})
    values = payoff(legs, points)
    breakevens = []
    for left, right, left_value, right_value in zip(points, points[1:], values, values[1:]):
        if left_value == 0:
            breakevens.append(left)
        if left_value * right_value < 0:
            ratio = abs(left_value) / (abs(left_value) + abs(right_value))
            breakevens.append(round(left + (right - left) * ratio, 8))
    if values[-1] == 0:
        breakevens.append(points[-1])
    return {
        "max_profit": None if max(values) == float("inf") else round(max(values), 8),
        "max_loss": None if min(values) == float("-inf") else round(min(values), 8),
        "breakevens": sorted(set(round(value, 8) for value in breakevens)),
    }
