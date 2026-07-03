"""FastAPI app.

REST handles session CRUD and file upload. The chat itself runs over a WebSocket so
the client sees tokens and tool steps live. Human-in-the-loop resume is handled
inline on the same socket: when the client gets an "interrupt" event it sends back
{"resume": {...}} and the run continues.
"""

from dotenv import load_dotenv
load_dotenv()

import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.agent.graph import graph_lifespan
from app.agent.runner import run_and_stream
from app.auth import get_current_user, verify_token
from app.models import ContactOut, SessionCreate, SessionOut, SessionUpdate, UploadOut, UserSetupRequest, UserSetupOut, WaitlistOut, WaitlistRequest
from app.services import database, mongo, storage

logger = logging.getLogger(__name__)

MONGODB_URI = os.environ["MONGODB_URI"]
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await mongo.connect(MONGODB_URI)
    await database.init_db()
    async with graph_lifespan(MONGODB_URI) as graph:
        app.state.graph = graph
        yield
    await mongo.close()


app = FastAPI(title="CardSync", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.api_route("/health", methods=["GET", "HEAD"])
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/users/setup", response_model=UserSetupOut)
async def user_setup(
    body: UserSetupRequest,
    user_id: str = Depends(get_current_user),
) -> UserSetupOut:
    """Get or create the user profile. Idempotent — safe to call on every login."""
    existing = await mongo.get_user(user_id)
    if existing:
        return UserSetupOut(
            scan_count=existing["scan_count"],
            notification_email=existing["notification_email"],
        )
    user = await mongo.create_user(user_id, email=body.email)
    return UserSetupOut(
        scan_count=user["scan_count"],
        notification_email=user["notification_email"],
    )


@app.post("/api/waitlist", response_model=WaitlistOut)
async def join_waitlist(body: WaitlistRequest) -> WaitlistOut:
    """Add an email to the waitlist. No auth required. Idempotent."""
    await mongo.add_to_waitlist(body.email)
    return WaitlistOut(status="added")


@app.get("/api/contacts", response_model=list[ContactOut])
async def get_contacts(
    user_id: str = Depends(get_current_user),
) -> list[ContactOut]:
    """Return all contacts belonging to the authenticated user."""
    return await database.get_contacts(user_id)


@app.get("/api/contacts/export")
async def export_contacts(
    user_id: str = Depends(get_current_user),
) -> Response:
    """Download all contacts for the authenticated user as a CSV file."""
    csv_data = await database.export_contacts_csv(user_id)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts.csv"},
    )


@app.post("/api/sessions", response_model=SessionOut)
async def create_session(
    body: SessionCreate,
    user_id: str = Depends(get_current_user),
) -> SessionOut:
    """Create a new chat session scoped to the authenticated user."""
    return await mongo.create_session(title=body.title, user_id=user_id)


@app.get("/api/sessions", response_model=list[SessionOut])
async def list_sessions(
    user_id: str = Depends(get_current_user),
) -> list[SessionOut]:
    """List sessions belonging to the authenticated user."""
    return await mongo.list_sessions(user_id=user_id)


@app.patch("/api/sessions/{session_id}", response_model=SessionOut)
async def rename_session(
    session_id: str,
    body: SessionUpdate,
    user_id: str = Depends(get_current_user),
) -> SessionOut:
    """Rename a session owned by the authenticated user."""
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title must not be empty")
    session = await mongo.rename_session(session_id, title, user_id=user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user),
) -> None:
    """Delete a session and its messages."""
    deleted = await mongo.delete_session(session_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    user_id: str = Depends(get_current_user),
) -> list:
    """Return message history for a session owned by the authenticated user."""
    session = await mongo.get_session(session_id, user_id=user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return await mongo.get_messages(session_id)


@app.post("/api/sessions/{session_id}/upload", response_model=UploadOut)
async def upload(
    session_id: str,
    file: UploadFile = File(...),
    kind: str = Form(...),
    user_id: str = Depends(get_current_user),
) -> UploadOut:
    """Save an image or audio file to R2 and return its key. Bytes never touch the LLM."""
    session = await mongo.get_session(session_id, user_id=user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    data = await file.read()
    key = f"{session_id}/{kind}/{uuid.uuid4()}-{file.filename}"
    await storage.save(key, data, content_type=file.content_type)
    return UploadOut(key=key, kind=kind)  # type: ignore[arg-type]


@app.websocket("/ws/sessions/{session_id}")
async def ws_chat(
    ws: WebSocket,
    session_id: str,
    token: str = Query(default=None),
) -> None:
    await ws.accept()

    # Authenticate via ?token= query param (browsers can't set WS headers).
    if not token:
        await ws.send_json({"type": "error", "data": "Unauthorized"})
        await ws.close(code=4001)
        return
    try:
        user_id = await verify_token(token)
    except HTTPException:
        await ws.send_json({"type": "error", "data": "Unauthorized"})
        await ws.close(code=4001)
        return

    # Verify the session belongs to this user before streaming.
    session = await mongo.get_session(session_id, user_id=user_id)
    if session is None:
        await ws.send_json({"type": "error", "data": "Session not found"})
        await ws.close(code=4001)
        return

    graph = ws.app.state.graph
    config = {"configurable": {"thread_id": session_id}}
    try:
        while True:
            incoming = await ws.receive_json()

            is_resume = "resume" in incoming
            if is_resume:
                stream_input = Command(resume=incoming["resume"])
            else:
                text = incoming.get("text") or "[media uploaded]"
                stream_input = {
                    "messages": [HumanMessage(content=text)],
                    "session_id": session_id,
                    "user_id": user_id,
                    # Reset each turn so stale keys never trigger re-processing.
                    "image_key": incoming.get("image_key"),
                    "audio_key": incoming.get("audio_key"),
                }
                await mongo.save_message(session_id, role="user", incoming=incoming)

            # Enforce the 2-scan free tier limit. Only card uploads count; resumes
            # and voice notes are never blocked.
            if not is_resume and incoming.get("image_key"):
                count = await mongo.get_scan_count(user_id)
                if count >= 2:
                    await ws.send_json({"type": "limit_reached", "data": {"scan_count": count}})
                    continue

            await run_and_stream(graph, stream_input, config, ws)

            if not is_resume and incoming.get("image_key"):
                await mongo.increment_scan_count(user_id)
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("ws_chat %s crashed", session_id)
        try:
            await ws.send_json({"type": "error", "data": "Internal server error"})
            await ws.close(code=1011)
        except Exception:
            pass
