"""Drives a graph run and pushes events to a WebSocket.

Uses astream with two stream modes at once:
  - "messages": token-by-token assistant output
  - "updates":  per-node updates, including "__interrupt__" when the graph pauses

Event shapes sent to the client:
  {"type": "token",     "data": "..."}                      assistant text chunk
  {"type": "tool",      "data": {"name": ..., "status": ...}} tool activity
  {"type": "interrupt", "data": {...}}                       HITL pause, awaiting resume
  {"type": "done",      "data": {}}                          run finished (or paused)
"""

from typing import Any

from langchain_core.messages import AIMessage


async def run_and_stream(graph, stream_input: Any, config: dict, ws) -> bool:
    """Run one graph turn and stream it. Returns True if it paused on an interrupt."""
    interrupted = False

    async for stream_mode, payload in graph.astream(
        stream_input, config=config, stream_mode=["updates", "messages"]
    ):
        if stream_mode == "messages":
            msg, meta = payload
            # Only stream the agent node's natural-language tokens.
            if meta.get("langgraph_node") == "agent" and getattr(msg, "content", None):
                await ws.send_json({"type": "token", "data": msg.content})

        elif stream_mode == "updates":
            if "__interrupt__" in payload:
                interrupt_obj = payload["__interrupt__"][0]
                await ws.send_json({"type": "interrupt", "data": interrupt_obj.value})
                interrupted = True
                continue

            for node_name, update in payload.items():
                # When the agent decides to call tools, announce them as "running".
                if node_name == "agent":
                    msgs = (update or {}).get("messages", [])
                    for m in msgs:
                        if isinstance(m, AIMessage):
                            for call in getattr(m, "tool_calls", []) or []:
                                await ws.send_json(
                                    {"type": "tool", "data": {"name": call["name"], "status": "running"}}
                                )
                # When the tools node finishes, announce them as "done".
                elif node_name == "tools":
                    msgs = (update or {}).get("messages", [])
                    for m in msgs:
                        name = getattr(m, "name", None)
                        if name:
                            await ws.send_json(
                                {"type": "tool", "data": {"name": name, "status": "done"}}
                            )

    if not interrupted:
        await ws.send_json({"type": "done", "data": {}})
    return interrupted
