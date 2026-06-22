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

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.agent.graph import graph_lifespan
from app.agent.runner import run_and_stream
from app.models import SessionCreate, SessionOut, SessionUpdate, UploadOut
from app.services import mongo, storage

logger = logging.getLogger(__name__)

MONGODB_URI = os.environ["MONGODB_URI"]
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await mongo.connect(MONGODB_URI)
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


@app.post("/api/sessions", response_model=SessionOut)
async def create_session(body: SessionCreate) -> SessionOut:
    return await mongo.create_session(title=body.title)


@app.get("/api/sessions", response_model=list[SessionOut])
async def list_sessions() -> list[SessionOut]:
    return await mongo.list_sessions()


@app.patch("/api/sessions/{session_id}", response_model=SessionOut)
async def rename_session(session_id: str, body: SessionUpdate) -> SessionOut:
    """Rename a session."""
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title must not be empty")
    session = await mongo.rename_session(session_id, title)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str) -> None:
    """Delete a session and its messages."""
    deleted = await mongo.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: str) -> list:
    return await mongo.get_messages(session_id)


@app.post("/api/sessions/{session_id}/upload", response_model=UploadOut)
async def upload(session_id: str, file: UploadFile = File(...), kind: str = Form(...)) -> UploadOut:
    """Save an image or audio file to R2 and return its key. Bytes never touch the LLM."""
    data = await file.read()
    key = f"{session_id}/{kind}/{uuid.uuid4()}-{file.filename}"
    await storage.save(key, data, content_type=file.content_type)
    return UploadOut(key=key, kind=kind)  # type: ignore[arg-type]


@app.websocket("/ws/sessions/{session_id}")
async def ws_chat(ws: WebSocket, session_id: str) -> None:
    await ws.accept()
    graph = ws.app.state.graph
    config = {"configurable": {"thread_id": session_id}}
    try:
        while True:
            incoming = await ws.receive_json()

            if "resume" in incoming:
                stream_input = Command(resume=incoming["resume"])
            else:
                text = incoming.get("text") or "[media uploaded]"
                stream_input = {
                    "messages": [HumanMessage(content=text)],
                    "session_id": session_id,
                    # Reset each turn so stale keys never trigger re-processing.
                    "image_key": incoming.get("image_key"),
                    "audio_key": incoming.get("audio_key"),
                }
                await mongo.save_message(session_id, role="user", incoming=incoming)

            await run_and_stream(graph, stream_input, config, ws)
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("ws_chat %s crashed", session_id)
        try:
            await ws.send_json({"type": "error", "data": "Internal server error"})
            await ws.close(code=1011)
        except Exception:
            pass
