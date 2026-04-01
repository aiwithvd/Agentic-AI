"""Define the state structures for the agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, List

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


@dataclass
class State:
    """Agent state carrying the full conversation message history.

    The `messages` field uses LangGraph's `add_messages` reducer so that
    appending new messages never clobbers existing ones.
    """

    messages: Annotated[List[AnyMessage], add_messages] = field(
        default_factory=list
    )
