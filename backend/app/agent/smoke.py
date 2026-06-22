"""Standalone agent smoke test. Run before building any endpoints.

    python -m app.agent.smoke

Drives the full two-flow sequence:
  Flow A (card): extract_card_details -> check_duplicate -> log_contact_to_sheet
                 (interrupt + confirm) -> send_whatsapp_alert
  Flow B (voice): store_voice_note -> updates the sheet row logged in Flow A

Uses an InMemorySaver so no MongoDB connection is needed. The checkpointer keeps
current_row_id alive across turns so Flow B can find the right row.
"""

import asyncio
import json

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.services import sheets, storage

IMAGE_PATH = "sample_card.jpg"
AUDIO_PATH = "sample_voice.ogg"
R2_IMAGE_KEY = "smoke/sample_card.jpg"
R2_AUDIO_KEY = "smoke/sample_voice.ogg"


def _print_node(node: str, data: dict) -> None:
    for m in data.get("messages", []):
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                args_str = json.dumps(tc["args"], ensure_ascii=False)
                print(f"  [{node}] TOOL CALL   {tc['name']}  {args_str}")
        elif isinstance(m, ToolMessage):
            print(f"  [{node}] TOOL RESULT  {str(m.content)[:300]}")
        elif m.content:
            label = type(m).__name__.replace("Message", "").upper()
            print(f"  [{node}] {label}  {m.content}")
    if data.get("current_row_id"):
        print(f"  [{node}] state.current_row_id = {data['current_row_id']}")


async def stream_run(graph, state_or_command, config) -> bool:
    """Stream one graph run, printing every event. Returns True if interrupted."""
    interrupted = False
    async for update in graph.astream(state_or_command, config, stream_mode="updates"):
        if "__interrupt__" in update:
            interrupted = True
            for iv in update["__interrupt__"]:
                print(f"\n  --- INTERRUPT ---")
                print(f"  Paused for confirmation: {iv.value}")
        else:
            for node, data in update.items():
                _print_node(node, data)
    return interrupted


SMOKE_EMAIL = "baibhavbaidya@gmail.com"


def _clear_smoke_row() -> None:
    """Delete any sheet row matching SMOKE_EMAIL so each run starts fresh."""
    ws = sheets._sheet()
    records = ws.get_all_values()  # includes header
    for i, row in enumerate(records[1:], start=2):  # row index is 1-based, skip header
        if row[2].strip().lower() == SMOKE_EMAIL.lower():
            ws.delete_rows(i)
            print(f"[setup] Deleted existing smoke row {i} from sheet.")
            return
    print("[setup] No existing smoke row found — sheet is clean.")


async def main() -> None:
    # ── Setup: clear stale smoke data, then upload both files to R2 ──────────
    _clear_smoke_row()
    print(f"[setup] Uploading {IMAGE_PATH} -> R2:{R2_IMAGE_KEY}")
    with open(IMAGE_PATH, "rb") as f:
        await storage.save(R2_IMAGE_KEY, f.read(), content_type="image/jpeg")

    print(f"[setup] Uploading {AUDIO_PATH} -> R2:{R2_AUDIO_KEY}")
    with open(AUDIO_PATH, "rb") as f:
        await storage.save(R2_AUDIO_KEY, f.read(), content_type="audio/ogg")

    print(f"[setup] Both files on R2.\n")

    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "smoke-1"}}

    # ── Turn 1: card upload ───────────────────────────────────────────────────
    print("=== Turn 1: card upload ===")
    interrupted = await stream_run(
        graph,
        {
            "messages": [HumanMessage(content="I just uploaded a visiting card.")],
            "session_id": "smoke-1",
            "image_key": R2_IMAGE_KEY,
            "audio_key": None,
        },
        config,
    )

    # ── Turn 2: edit the extracted contact (name fix: all-caps → proper case) ──
    if interrupted:
        print("\n=== Turn 2: editing contact (name correction) ===")
        await stream_run(
            graph,
            Command(resume={"decision": "edit", "edits": {"name": "Baibhav Baidya"}}),
            config,
        )

    # ── Turn 3: voice note in the same session ────────────────────────────────
    print("\n=== Turn 3: voice note ===")
    interrupted = await stream_run(
        graph,
        {
            "messages": [HumanMessage(content="Here's a voice note about this contact.")],
            "image_key": None,
            "audio_key": R2_AUDIO_KEY,
        },
        config,
    )

    if interrupted:
        print("\n=== Turn 3 (resume): editing transcript ===")
        await stream_run(
            graph,
            Command(resume={
                "decision": "edit",
                "transcript": "Baibhav at the conference. He is interested in the enterprise plan. I'll follow up next week.",
            }),
            config,
        )

    print("\n=== Smoke test complete ===")


if __name__ == "__main__":
    asyncio.run(main())
