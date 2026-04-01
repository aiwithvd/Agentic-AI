"""LangGraph chatbot agent backed by a real LLM via LangChain."""

from __future__ import annotations

from typing import Any, Dict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph

from agent.configuration import Configuration
from agent.state import State


async def call_model(state: State, config: RunnableConfig) -> Dict[str, Any]:
    """Invoke the configured LLM with the current message history."""
    configuration = Configuration.from_runnable_config(config)

    llm = ChatAnthropic(model=configuration.model)

    # Prepend the system prompt so it always takes effect regardless of
    # what messages are already in state.
    messages = [SystemMessage(content=configuration.system_prompt)] + list(
        state.messages
    )

    response = await llm.ainvoke(messages)
    return {"messages": [response]}


# ── Graph construction ────────────────────────────────────────────────────────

workflow = StateGraph(State, config_schema=Configuration)
workflow.add_node("call_model", call_model)
workflow.add_edge("__start__", "call_model")

# Compiled without a checkpointer — used by LangGraph Studio.
# The FastAPI app compiles its own copy with AsyncPostgresSaver at startup.
graph = workflow.compile()
graph.name = "Chatbot"
