"""Agent tools.

Every external integration is a tool here. Tools read the heavy stuff (files,
the active row) from injected state, not from LLM-supplied arguments, so the LLM
cannot hallucinate file keys or row ids.

State updates that must persist (current_row_id) are returned as a Command, which
LangGraph applies to the graph state and the MongoDB checkpointer saves.
"""

import logging
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, interrupt

from app.services import llm, sheets, storage, whatsapp

logger = logging.getLogger(__name__)


@tool
def extract_card_details(state: Annotated[dict, InjectedState]) -> dict:
    """Extract Name, Phone, Email, and Company from the uploaded visiting card image."""
    image_key = state.get("image_key")
    if not image_key:
        return {"error": "No card image was uploaded in this turn. Ask the user to upload one."}
    # TODO: implement in services/llm.py (download from R2, gpt-4o vision, Pydantic schema)
    return llm.extract_card(image_key)


@tool
def check_duplicate(email: str, phone: str) -> dict:
    """Check whether a contact with this email or phone already exists in the sheet."""
    # TODO: implement in services/sheets.py (normalize email + phone, scan rows)
    return sheets.find_duplicate(email=email, phone=phone)


@tool
def log_contact_to_sheet(
    contact: dict,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Append a confirmed contact to the Google Sheet and remember it as the active card.

    Pauses for human confirmation BEFORE writing. The interrupt is the first action so
    that on resume the node re-runs cleanly with no duplicate write (resumed nodes
    re-execute from the top).
    """
    # 1. Confirm first. Nothing with side effects runs before this line.
    decision = interrupt({"action": "confirm_contact", "contact": contact})

    if decision.get("decision") == "reject":
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "User rejected the extracted details. Ask them to re-upload a clearer card.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    # 2. Apply any edits the user made in the confirmation step, then write.
    # Merge session_id from state — the LLM's tool args never include it.
    final_contact = {**contact, **decision.get("edits", {}), "session_id": state.get("session_id", "")}
    row_id = sheets.append_contact(final_contact)

    # 3. Persist the active row into state so the voice-note tool can find it later.
    return Command(
        update={
            "current_row_id": row_id,
            "messages": [
                ToolMessage(
                    f"Logged contact to the sheet (row {row_id}). "
                    f"Final details — name: {final_contact['name']}, "
                    f"company: {final_contact['company']}, "
                    f"email: {final_contact['email']}, "
                    f"phone: {final_contact['phone']}.",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


@tool
def send_whatsapp_alert(name: str, company: str) -> str:
    """Send the manager a WhatsApp alert that a new card was logged."""
    # TODO: implement in services/whatsapp.py (Meta Cloud API template message)
    status = whatsapp.send_alert(name=name, company=company)
    return f"WhatsApp alert sent ({status})."


@tool
def store_voice_note(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Attach the uploaded voice note to the card logged earlier in this session.

    Transcribes first, then pauses for the user to review and correct the transcript
    before writing it to the sheet.
    """
    row_id = state.get("current_row_id")
    audio_key = state.get("audio_key")
    if not row_id:
        return "No card has been logged in this session yet. Ask the user to upload a visiting card first."
    if not audio_key:
        return "No voice note was uploaded in this turn."

    # Transcribe before interrupting so the user sees the actual text.
    # On resume the tool re-runs from the top, so Whisper is called twice — acceptable for a prototype.
    audio_url = storage.public_url(audio_key)
    transcript = llm.transcribe(audio_key)

    decision = interrupt({"action": "confirm_transcript", "transcript": transcript, "audio_url": audio_url})

    if decision.get("decision") == "reject":
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Transcript rejected. Ask the user to re-record the voice note.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    final_transcript = decision.get("transcript", transcript)
    sheets.update_audio(row_id=row_id, audio_url=audio_url, transcript=final_transcript)

    return Command(
        update={
            "messages": [
                ToolMessage(
                    f"Voice note attached to the contact in row {row_id}.",
                    tool_call_id=tool_call_id,
                )
            ]
        }
    )


@tool
def enrich_company(
    company: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """Find the company's website and LinkedIn URL and write them to the logged contact row.

    Called after send_whatsapp_alert. Reads current_row_id from state so the LLM
    cannot hallucinate which row to update. Fails gracefully — never blocks the flow.
    """
    row_id = state.get("current_row_id")
    if not row_id:
        return "No contact has been logged in this session yet — enrichment skipped."

    try:
        result = llm.enrich_company(company)
        website = result.get("website") or ""
        linkedin = result.get("linkedin") or ""
        if not website and not linkedin:
            logger.warning("enrich_company: no data found for %r", company)
            return "enrichment skipped"
        sheets.update_enrichment(row_id=row_id, website=website, linkedin=linkedin)
        return (
            f"Enrichment complete — website: {website or 'not found'}, "
            f"LinkedIn: {linkedin or 'not found'}."
        )
    except Exception as exc:
        logger.warning("enrich_company failed for %r: %s", company, exc)
        return "enrichment skipped"


ALL_TOOLS = [
    extract_card_details,
    check_duplicate,
    log_contact_to_sheet,
    send_whatsapp_alert,
    store_voice_note,
    enrich_company,
]
