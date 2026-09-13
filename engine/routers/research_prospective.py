"""Read-only endpoints for archiving prospective real-data evidence."""

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

router = APIRouter(prefix="/api/research/prospective", tags=["research"])


@router.get("/status")
async def prospective_status():
    """Return the accumulated observation/maturation milestone without secrets."""
    from research.prospective_store import get_status

    return get_status()


@router.get("/export")
async def prospective_export():
    """Download a fresh R1-compatible SQLite export without mutating evidence."""
    from research.prospective_store import export_r1

    handle = tempfile.NamedTemporaryFile(prefix="fortress-r1-", suffix=".sqlite", delete=False)
    handle.close()
    path = Path(handle.name)
    try:
        result = export_r1(str(path))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return FileResponse(
        result["path"],
        media_type="application/vnd.sqlite3",
        filename="fortress-r1-prospective.sqlite",
        background=BackgroundTask(lambda: os.unlink(result["path"])),
    )
