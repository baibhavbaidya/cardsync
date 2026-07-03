"""MongoDB: sessions and message history for the UI.

The LangGraph checkpointer manages its own collections separately. This module is
only for the session list and rendering chat history.
"""

import uuid
from datetime import datetime, timezone

from pymongo import AsyncMongoClient

from app.services import storage

_client: AsyncMongoClient | None = None
_db = None


async def connect(uri: str, db_name: str = "card_orchestrator") -> None:
    global _client, _db
    _client = AsyncMongoClient(uri)
    _db = _client[db_name]


async def close() -> None:
    if _client is not None:
        await _client.close()


async def create_session(title: str, user_id: str) -> dict:
    now = datetime.now(timezone.utc)
    doc = {
        "session_id": str(uuid.uuid4()),
        "user_id": user_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
    }
    await _db["sessions"].insert_one(doc)
    doc.pop("_id", None)
    return doc


async def list_sessions(user_id: str) -> list:
    cursor = _db["sessions"].find(
        {"user_id": user_id}, {"_id": 0, "user_id": 0}
    ).sort("created_at", -1)
    return await cursor.to_list(length=200)


async def get_session(session_id: str, user_id: str) -> dict | None:
    """Return a session only if it belongs to the given user."""
    return await _db["sessions"].find_one(
        {"session_id": session_id, "user_id": user_id}, {"_id": 0, "user_id": 0}
    )


async def save_message(session_id: str, role: str, incoming: dict) -> None:
    now = datetime.now(timezone.utc)

    if incoming.get("image_key"):
        msg_type, media_url = "image", storage.public_url(incoming["image_key"])
    elif incoming.get("audio_key"):
        msg_type, media_url = "audio", storage.public_url(incoming["audio_key"])
    else:
        msg_type, media_url = "text", None

    await _db["messages"].insert_one({
        "session_id": session_id,
        "role": role,
        "type": msg_type,
        "content": incoming.get("text"),
        "media_url": media_url,
        "created_at": now,
    })
    await _db["sessions"].update_one(
        {"session_id": session_id},
        {"$set": {"updated_at": now}},
    )


async def rename_session(session_id: str, title: str, user_id: str) -> dict | None:
    now = datetime.now(timezone.utc)
    result = await _db["sessions"].update_one(
        {"session_id": session_id, "user_id": user_id},
        {"$set": {"title": title, "updated_at": now}},
    )
    if result.matched_count == 0:
        return None
    return await _db["sessions"].find_one(
        {"session_id": session_id}, {"_id": 0, "user_id": 0}
    )


async def delete_session(session_id: str, user_id: str) -> bool:
    result = await _db["sessions"].delete_one({"session_id": session_id, "user_id": user_id})
    if result.deleted_count > 0:
        await _db["messages"].delete_many({"session_id": session_id})
    return result.deleted_count > 0


async def get_messages(session_id: str) -> list:
    cursor = _db["messages"].find(
        {"session_id": session_id},
        {"_id": 0},
    ).sort("created_at", 1)
    return await cursor.to_list(length=1000)


# ── User profile ──────────────────────────────────────────────────────────


async def get_user(user_id: str) -> dict | None:
    return await _db["users"].find_one({"user_id": user_id}, {"_id": 0})


async def create_user(user_id: str, email: str) -> dict:
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": user_id,
        "email": email,
        "scan_count": 0,
        "notification_email": email,
        "created_at": now,
    }
    await _db["users"].insert_one(doc)
    doc.pop("_id", None)
    return doc


async def get_scan_count(user_id: str) -> int:
    user = await _db["users"].find_one({"user_id": user_id}, {"scan_count": 1})
    return user["scan_count"] if user else 0


async def increment_scan_count(user_id: str) -> None:
    await _db["users"].update_one({"user_id": user_id}, {"$inc": {"scan_count": 1}})


# ── Waitlist ──────────────────────────────────────────────────────────────


async def add_to_waitlist(email: str) -> None:
    """Idempotent — upserts so duplicate emails are silently ignored."""
    await _db["waitlist"].update_one(
        {"email": email},
        {"$setOnInsert": {"email": email, "created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
