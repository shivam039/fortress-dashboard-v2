"""Read-only deterministic Oracle Decision API."""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_utils import get_current_user

router = APIRouter(prefix="/api/oracle-decision", tags=["oracle-decision"])


class OracleRequest(BaseModel):
    signal_id: int = Field(..., gt=0)


class MaturationRequest(BaseModel):
    limit: int = Field(default=200, ge=1, le=200)


@router.post("")
async def oracle_decision(body: OracleRequest, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    from oracle_decision.service import build_decision
    from utils.db import fetch_signal_ledger

    matches = fetch_signal_ledger(signal_id=body.signal_id, limit=1)
    if not matches:
        raise HTTPException(status_code=404, detail="Scanner signal not found")
    return build_decision(matches[0])


@router.post("/outcomes/mature")
async def mature_oracle_outcomes(body: MaturationRequest) -> Dict[str, Any]:
    from oracle_outcomes.service import mature_pending
    return mature_pending(body.limit)


@router.get("/{signal_id}/outcomes")
async def oracle_outcomes(signal_id: int, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Read-only local outcome calculation for one persisted signal."""
    from oracle_outcomes.service import evaluate_outcomes
    from utils.db import fetch_signal_ledger, fetch_oracle_outcomes
    from utils.market_data_provider import get_ohlcv

    matches = fetch_signal_ledger(signal_id=signal_id, limit=1)
    if not matches:
        raise HTTPException(status_code=404, detail="Scanner signal not found")
    signal = matches[0]
    persisted = fetch_oracle_outcomes(signal_id=signal_id)
    if persisted:
        return {"signal_id": signal_id, "oracle_version": "oracle-v1", "outcomes": persisted}
    history = get_ohlcv(signal["symbol"], "1y")
    bars = []
    if history is not None and not history.empty:
        for timestamp, row in history.iterrows():
            bars.append({"date": timestamp.strftime("%Y-%m-%d"), "close": row.get("Close")})
    decision = build_decision(signal)
    signal["oracle_decision"] = decision["decision"]
    return {"signal_id": signal_id, "oracle_version": "oracle-v1", "outcomes": evaluate_outcomes(signal, bars)}


@router.get("/performance")
async def oracle_performance(decision: Optional[str] = None, horizon: Optional[int] = None, user: dict = Depends(get_current_user)):
    from oracle_outcomes.service import scorecard
    from utils.db import fetch_oracle_outcomes
    return {"scorecard": scorecard(fetch_oracle_outcomes(decision=decision, horizon=horizon))}
