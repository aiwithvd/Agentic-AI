"""Repository layer: data-access abstractions over Thread ORM model."""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.db.models import Thread


class ThreadRepository:
    """All database operations for Thread objects."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        title: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Thread:
        """Insert a new Thread and return it."""
        thread = Thread(title=title, metadata_=metadata)
        self._session.add(thread)
        await self._session.flush()
        await self._session.refresh(thread)
        return thread

    async def get_by_id(self, thread_id: uuid.UUID) -> Optional[Thread]:
        """Return a Thread or None."""
        result = await self._session.execute(
            select(Thread).where(Thread.id == thread_id)
        )
        return result.scalar_one_or_none()

    async def list_paginated(
        self, limit: int = 20, offset: int = 0
    ) -> Tuple[List[Thread], int]:
        """Return (threads, total_count) ordered newest-first."""
        count_result = await self._session.execute(
            select(func.count()).select_from(Thread)
        )
        total = count_result.scalar_one()

        threads_result = await self._session.execute(
            select(Thread)
            .order_by(Thread.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(threads_result.scalars().all()), total

    async def delete(self, thread_id: uuid.UUID) -> bool:
        """Delete a Thread; return True if it existed."""
        thread = await self.get_by_id(thread_id)
        if thread is None:
            return False
        await self._session.delete(thread)
        return True
