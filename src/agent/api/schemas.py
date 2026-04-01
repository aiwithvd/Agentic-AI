"""Pydantic request/response schemas for the HTTP API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Requests ─────────────────────────────────────────────────────────────────

class CreateThreadRequest(BaseModel):
    """Body for POST /api/v1/threads."""

    title: Optional[str] = Field(default=None, max_length=500)
    metadata: Optional[Dict[str, Any]] = None


class SendMessageRequest(BaseModel):
    """Body for POST /api/v1/threads/{thread_id}/messages."""

    content: str = Field(..., min_length=1, max_length=32_000)
    model: Optional[str] = Field(
        default=None,
        description="Override the LLM model for this request.",
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="Override the system prompt for this request.",
    )


# ── Responses ────────────────────────────────────────────────────────────────

class MessageOut(BaseModel):
    """A single message in a conversation."""

    role: str
    content: str


class ThreadResponse(BaseModel):
    """Serialised Thread metadata (list view)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(None, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ThreadDetailResponse(ThreadResponse):
    """Thread metadata including full message history."""

    messages: List[MessageOut] = []


class PaginatedThreadsResponse(BaseModel):
    """Paginated list of threads."""

    items: List[ThreadResponse]
    total: int
    limit: int
    offset: int


class SendMessageResponse(BaseModel):
    """Response after the agent processes a user message."""

    thread_id: uuid.UUID
    user_message: str
    assistant_message: str
    cached: bool = False


class HealthResponse(BaseModel):
    """Health check result."""

    status: str
    database: str
    redis: str
