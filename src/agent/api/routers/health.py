"""Health check endpoint: verifies DB and Redis connectivity."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from agent.api.schemas import HealthResponse
from agent.cache.redis_client import get_redis_client
from agent.db.engine import get_engine

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check database and Redis connectivity."""
    db_status = "ok"
    redis_status = "ok"

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    try:
        client = get_redis_client()
        await client.ping()
    except Exception:
        redis_status = "error"

    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"
    return HealthResponse(status=overall, database=db_status, redis=redis_status)
