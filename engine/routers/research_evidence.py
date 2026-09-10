# engine/routers/research_evidence.py — FORTRESS-V2: read-only real
# historical-evidence lookup for the Fortress Score UI.
"""
- GET /api/research-evidence → real FORTRESS-R2 evidence for a score/horizon.

Serves whatever the latest real R2 validation result on disk says (see
engine/utils/research_evidence.py) — never recomputes the research
pipeline per request, never fabricates a value. Authenticated like every
other account-scoped endpoint; this is not public market data.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth_utils import get_current_user

router = APIRouter(prefix="/api/research-evidence", tags=["research"])

_VALID_HORIZONS = (5, 10, 20, 60)


@router.get("")
async def research_evidence(
    score: float = Query(..., ge=0, le=100, description="Current Fortress Score (0-100)"),
    horizon: int = Query(20, description="Forward-return horizon in trading sessions"),
    regime: Optional[str] = Query(None, description="Current market regime, e.g. 'Bull'"),
    user: dict = Depends(get_current_user),
):
    """Real R2-derived historical evidence for a current Fortress score.

    Always returns 200 with `available: true/false` — a missing or
    insufficient real result is not an error, it's the honest answer.
    """
    from utils.research_evidence import get_evidence

    if horizon not in _VALID_HORIZONS:
        horizon = 20

    return get_evidence(score=score, horizon=horizon, regime=regime)
