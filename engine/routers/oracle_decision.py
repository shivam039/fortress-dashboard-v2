"""Read-only deterministic Oracle Decision API."""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_utils import get_current_user

router = APIRouter(prefix="/api/oracle-decision", tags=["oracle-decision"])


class OracleRequest(BaseModel):
    signal_id: int = Field(..., gt=0)


@router.post("")
async def oracle_decision(body: OracleRequest, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    from oracle_decision.service import build_decision
    from utils.db import fetch_signal_ledger

    matches = fetch_signal_ledger(signal_id=body.signal_id, limit=1)
    if not matches:
        raise HTTPException(status_code=404, detail="Scanner signal not found")
    return build_decision(matches[0])
