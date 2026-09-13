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
    """Calculate theoretical risk metrics and supplied-grid extrema.

    The underlying domain is ``[price_floor, infinity)``. ``max_profit`` or
    ``max_loss`` is ``None`` when the tail is unbounded. ``grid_*`` values are
    explicitly limited to the exploration range and are never presented as
    theoretical limits.
    """
    if not legs:
        return {"max_profit": None, "max_loss": None, "breakevens": [],
                "grid_max_profit": None, "grid_max_loss": None}
    ceiling = price_ceiling or max(leg.strike for leg in legs) * 2.0
    if ceiling <= price_floor:
        raise ValueError("price_ceiling must exceed price_floor")
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
    # Above the highest strike, only calls contribute slope. A positive
    # slope is an unbounded profit tail; a negative slope is an unbounded
    # loss tail. The lower tail is bounded by the non-negative floor.
    upper_slope = sum(
        (1.0 if leg.side == "BUY" else -1.0) * leg.quantity
        for leg in legs if leg.option_type == "CE"
    )
    grid_profit = round(max(values), 8)
    grid_loss = round(min(values), 8)
    return {
        "max_profit": None if upper_slope > 0 else grid_profit,
        "max_loss": None if upper_slope < 0 else grid_loss,
        "breakevens": sorted(set(round(value, 8) for value in breakevens)),
        "grid_max_profit": grid_profit,
        "grid_max_loss": grid_loss,
    }
