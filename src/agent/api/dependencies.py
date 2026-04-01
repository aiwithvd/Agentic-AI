"""FastAPI dependency-injection functions."""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent.cache.redis_client import check_rate_limit
from agent.db.engine import get_session_factory
from agent.db.repositories import ThreadRepository


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session scoped to the HTTP request.

    The `session.begin()` context manager commits on clean exit and
    rolls back automatically on any unhandled exception.
    """
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            yield session


def get_thread_repo(
    session: AsyncSession = Depends(get_db),
) -> ThreadRepository:
    """Return a ThreadRepository bound to the current request's session."""
    return ThreadRepository(session)


async def rate_limit(request: Request) -> None:
    """Raise HTTP 429 when the calling IP has exceeded the rate limit."""
    client_ip = request.client.host if request.client else "unknown"
    allowed = await check_rate_limit(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down.",
            headers={"Retry-After": "60"},
        )
