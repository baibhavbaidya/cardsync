"""The single tool-calling agent.

Graph shape:
    START -> agent
    agent -> tools   (when the model returned tool calls)
    agent -> END     (when the model returned a final answer)
    tools -> agent   (loop)

One agent, many tools. The model decides which tool to call. Do not turn this into
a fixed node chain or multiple agents.
"""

from contextlib import asynccontextmanager

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pymongo import MongoClient

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import AgentState
from app.agent.tools import ALL_TOOLS

_model = ChatOpenAI(model="gpt-4o", temperature=0).bind_tools(ALL_TOOLS)


async def agent_node(state: AgentState) -> dict:
    """Call the model with the system prompt prepended."""
    messages = [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
    response = await _model.ainvoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    """Route to tools if the last message asked for any, otherwise end."""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


def build_graph(checkpointer) -> "CompiledStateGraph":
    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(ALL_TOOLS))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue, ["tools", END])
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)


@asynccontextmanager
async def graph_lifespan(mongodb_uri: str):
    """Compile the graph with a MongoDB checkpointer for the app lifetime.

    Note: this package version (langgraph-checkpoint-mongodb 0.4.0) ships only the
    sync `MongoDBSaver`. It still exposes async methods (aput/aget/alist), which
    LangGraph runs in a threadpool, so it works fine under async `astream`/`ainvoke`.

    Usage in main.py:
        async with graph_lifespan(MONGODB_URI) as graph:
            app.state.graph = graph
            yield
    """
    client = MongoClient(mongodb_uri)
    try:
        checkpointer = MongoDBSaver(client, db_name="card_orchestrator")
        yield build_graph(checkpointer)
    finally:
        client.close()
