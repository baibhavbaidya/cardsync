"""LangGraph agent state.

The whole orchestration hangs off this. `current_row_id` is the link between a
card and a later voice note: it is written by `log_contact_to_sheet` and read by
`store_voice_note`. It persists per thread_id (= session_id) via the MongoDB
checkpointer, so it survives across separate WebSocket turns in the same session.
"""

from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    session_id: str

    # R2 keys for the files uploaded this turn. Set by the WebSocket handler,
    # read by the extract / voice tools. Never carry raw bytes here.
    image_key: Optional[str]
    audio_key: Optional[str]

    # The active card for this session. Written when a contact is logged,
    # read when a voice note arrives. This is the crux of the assignment.
    current_row_id: Optional[str]

    # The authenticated user. Set from the verified JWT on every WebSocket turn
    # so tools always have it in scope without the LLM touching it.
    user_id: Optional[str]
