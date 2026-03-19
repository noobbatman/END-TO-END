"""Health check routes — liveness and readiness probes."""
from fastapi import APIRouter, Depends
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import db_dependency
from app.core.config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/health")
@router.get("/health/live")       # ← Kubernetes liveness alias
def liveness() -> dict:
    """Fast liveness probe — no DB check, just confirms process is alive."""
    return {"status": "ok", "version": settings.pipeline_version}


@router.get("/health/ready")      # ← Kubernetes readiness probe
def readiness(db: Session = Depends(db_dependency)) -> dict:
    """Readiness probe — confirms database is reachable before accepting traffic."""
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    payload = {
        "status": "ok" if db_ok else "degraded",
        "version": settings.pipeline_version,
        "env": settings.app_env,
        "storage_backend": settings.storage_backend,
        "database": "ok" if db_ok else "error",
    }
    if db_ok:
        return payload
    return JSONResponse(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
