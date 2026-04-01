"""CRUD endpoints for conversation threads and messages."""

from __future__ import annotations

import uuid
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from langchain_core.messages import AIMessage, HumanMessage

from agent.api.dependencies import get_thread_repo, rate_limit
from agent.api.schemas import (
    CreateThreadRequest,
    MessageOut,
    PaginatedThreadsResponse,
    SendMessageRequest,
    SendMessageResponse,
    ThreadDetailResponse,
    ThreadResponse,
)
from agent.cache.redis_client import get_cached_response, set_cached_response
from agent.db.repositories import ThreadRepository

router = APIRouter(
    prefix="/api/v1/threads",
    tags=["threads"],
    dependencies=[Depends(rate_limit)],
)


@router.post(
    "",
    response_model=ThreadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_thread(
    body: CreateThreadRequest,
    thread_repo: ThreadRepository = Depends(get_thread_repo),
) -> ThreadResponse:
    """Create a new conversation thread."""
    thread = await thread_repo.create(title=body.title, metadata=body.metadata)
    return ThreadResponse.model_validate(thread)


@router.get("", response_model=PaginatedThreadsResponse)
async def list_threads(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    thread_repo: ThreadRepository = Depends(get_thread_repo),
) -> PaginatedThreadsResponse:
    """Return a paginated list of threads, newest first."""
    threads, total = await thread_repo.list_paginated(limit=limit, offset=offset)
    return PaginatedThreadsResponse(
        items=[ThreadResponse.model_validate(t) for t in threads],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{thread_id}", response_model=ThreadDetailResponse)
async def get_thread(
    thread_id: uuid.UUID,
    request: Request,
    thread_repo: ThreadRepository = Depends(get_thread_repo),
) -> ThreadDetailResponse:
    """Return thread metadata and its full message history from LangGraph."""
    thread = await thread_repo.get_by_id(thread_id)
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found.",
        )

    # Load message history from LangGraph checkpoint
    graph = request.app.state.graph
    state_snapshot = await graph.aget_state(
        {"configurable": {"thread_id": str(thread_id)}}
    )

    messages: List[MessageOut] = []
    if state_snapshot and state_snapshot.values:
        for msg in state_snapshot.values.get("messages", []):
            if isinstance(msg, HumanMessage):
                role = "human"
            elif isinstance(msg, AIMessage):
                role = "assistant"
            else:
                role = msg.__class__.__name__.lower().replace("message", "")
            content = (
                msg.content
                if isinstance(msg.content, str)
                else str(msg.content)
            )
            messages.append(MessageOut(role=role, content=content))

    detail = ThreadDetailResponse.model_validate(thread)
    detail.messages = messages
    return detail


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: uuid.UUID,
    thread_repo: ThreadRepository = Depends(get_thread_repo),
) -> None:
    """Delete a thread and its checkpoint data."""
    deleted = await thread_repo.delete(thread_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found.",
        )


@router.post("/{thread_id}/messages", response_model=SendMessageResponse)
async def send_message(
    thread_id: uuid.UUID,
    body: SendMessageRequest,
    request: Request,
    thread_repo: ThreadRepository = Depends(get_thread_repo),
) -> SendMessageResponse:
    """Send a user message and receive the agent's response.

    Checks the Redis response cache first. On a miss, invokes the LangGraph
    agent (which persists state via AsyncPostgresSaver automatically), caches
    the result, and returns it.
    """
    thread = await thread_repo.get_by_id(thread_id)
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found.",
        )

    str_thread_id = str(thread_id)

    # ── Cache check ───────────────────────────────────────────────────────
    cached = await get_cached_response(str_thread_id, body.content)
    if cached is not None:
        return SendMessageResponse(
            thread_id=thread_id,
            user_message=cached["user_message"],
            assistant_message=cached["assistant_message"],
            cached=True,
        )

    # ── Build LangGraph config ────────────────────────────────────────────
    configurable: dict = {"thread_id": str_thread_id}
    if body.model:
        configurable["model"] = body.model
    if body.system_prompt:
        configurable["system_prompt"] = body.system_prompt

    # ── Invoke the agent ──────────────────────────────────────────────────
    graph = request.app.state.graph
    result_state = await graph.ainvoke(
        {"messages": [HumanMessage(content=body.content)]},
        config={"configurable": configurable},
    )

    # Extract the assistant's reply (last message in returned state)
    last_msg = result_state["messages"][-1]
    assistant_content: str = (
        last_msg.content
        if isinstance(last_msg.content, str)
        else str(last_msg.content)
    )

    # ── Cache and return ──────────────────────────────────────────────────
    payload = {
        "user_message": body.content,
        "assistant_message": assistant_content,
    }
    await set_cached_response(str_thread_id, body.content, payload)

    return SendMessageResponse(
        thread_id=thread_id,
        user_message=body.content,
        assistant_message=assistant_content,
        cached=False,
    )
