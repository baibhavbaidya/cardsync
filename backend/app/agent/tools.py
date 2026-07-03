"""Agent tools.

Every external integration is a tool here. Tools read the heavy stuff (files,
the active row, user_id) from injected state, not from LLM-supplied arguments,
so the LLM cannot hallucinate file keys, row IDs, or user identities.

State updates that must persist (current_row_id) are returned as a Command, which
LangGraph applies to the graph state and the MongoDB checkpointer saves.

Tools that call the Postgres database or MongoDB are async.
"""

import asyncio
import logging
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, interrupt

from app.services import database, email as email_svc, llm, mongo, storage

logger = logging.getLogger(__name__)


def _require_user_id(state: dict) -> str | None:
    return state.get("user_id") or None


@tool
def extract_card_details(state: Annotated[dict, InjectedState]) -> dict:
    """Extract Name, Phone, Email, and Company from the uploaded visiting card image."""
    image_key = state.get("image_key")
    if not image_key:
        return {"error": "No card image was uploaded in this turn. Ask the user to upload one."}
    return llm.extract_card(image_key)


@tool
async def check_duplicate(
    email: str,
    phone: str,
    state: Annotated[dict, InjectedState],
) -> dict:
    """Check whether a contact with this email or phone already exists."""
    user_id = _require_user_id(state)
    if not user_id:
        return {"error": "User not identified. Please refresh the page."}
    return await database.find_duplicate(user_id=user_id, email=email, phone=phone)


@tool
async def log_contact_to_sheet(
    contact: dict,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Save a confirmed contact to the database and remember it as the active card.

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

    user_id = _require_user_id(state)
    if not user_id:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "User not identified — contact not logged.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    # 2. Apply any edits the user made in the confirmation step, then write.
    final_contact = {**contact, **decision.get("edits", {}), "session_id": state.get("session_id", "")}
    contact_id = await database.insert_contact(user_id=user_id, contact=final_contact)

    # 3. Persist the active contact UUID into state so the voice-note tool can find it later.
    return Command(
        update={
            "current_row_id": contact_id,
            "messages": [
                ToolMessage(
                    f"Logged contact (id: {contact_id}). "
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
async def send_email_alert(
    name: str,
    company: str,
    phone: str,
    email: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """Email the logged-in user a notification that a new contact was saved."""
    user_id = _require_user_id(state)
    if not user_id:
        return "Email alert skipped — user not identified."
    user = await mongo.get_user(user_id)
    if not user or not user.get("notification_email"):
        return "Email alert skipped — no notification email on file."
    to_email = user["notification_email"]
    status = await asyncio.to_thread(
        email_svc.send_alert,
        name=name, company=company, phone=phone, email=email, to_email=to_email,
    )
    return f"Email alert {status} to {to_email}."


@tool
async def store_voice_note(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Attach the uploaded voice note to the card logged earlier in this session.

    Transcribes first, then pauses for the user to review and correct the transcript
    before writing it to the database.
    """
    contact_id = state.get("current_row_id")
    audio_key = state.get("audio_key")

    if not contact_id:
        return "No card has been logged in this session yet. Ask the user to upload a visiting card first."
    if not audio_key:
        return "No voice note was uploaded in this turn."

    # Transcribe before interrupting so the user sees the actual text.
    # On resume the tool re-runs from the top, so Whisper is called twice — acceptable for a prototype.
    audio_url = storage.public_url(audio_key)
    transcript = await asyncio.to_thread(llm.transcribe, audio_key)

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
    await database.update_audio(contact_id=contact_id, audio_url=audio_url, transcript=final_transcript)

    return Command(
        update={
            "messages": [
                ToolMessage(
                    f"Voice note attached to contact {contact_id}.",
                    tool_call_id=tool_call_id,
                )
            ]
        }
    )


@tool
async def enrich_company(
    company: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """Find the company's website and LinkedIn URL and write them to the logged contact.

    Called after send_email_alert. Reads current_row_id from state so the LLM
    cannot hallucinate which contact to update. Fails gracefully — never blocks the flow.
    """
    contact_id = state.get("current_row_id")

    if not contact_id:
        return "No contact has been logged in this session yet — enrichment skipped."

    try:
        result = await asyncio.to_thread(llm.enrich_company, company)
        website = result.get("website") or ""
        linkedin = result.get("linkedin") or ""
        if not website and not linkedin:
            logger.warning("enrich_company: no data found for %r", company)
            return "enrichment skipped"
        await database.update_enrichment(contact_id=contact_id, website=website, linkedin=linkedin)
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
    send_email_alert,
    store_voice_note,
    enrich_company,
]
