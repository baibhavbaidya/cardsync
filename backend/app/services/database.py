"""Neon Postgres contact store using async SQLAlchemy + asyncpg."""

import csv
import io
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

from sqlalchemy import Column, DateTime, String, Text, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_parsed = urlparse(os.environ["DATABASE_URL"])

engine = create_async_engine(
    "postgresql+asyncpg://",
    connect_args={
        "host": _parsed.hostname,
        "port": _parsed.port or 5432,
        "user": _parsed.username,
        "password": unquote(_parsed.password),
        "database": _parsed.path.lstrip("/").split("?")[0],
        "ssl": "require",
    },
    echo=False,
)
_Session = async_sessionmaker(engine, expire_on_commit=False)


class _Base(DeclarativeBase):
    pass


class _Contact(_Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False, default="")
    phone = Column(String, default="")
    email = Column(String, default="")
    company = Column(String, default="")
    website = Column(String, default="")
    linkedin = Column(String, default="")
    audio_url = Column(String, default="")
    transcript = Column(Text, default="")
    session_id = Column(String, default="")
    created_at = Column(DateTime(timezone=True))


async def init_db() -> None:
    """Create tables if they don't exist. Called once at startup."""
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _norm_phone(phone) -> str:
    return "".join(ch for ch in (str(phone) if phone else "") if ch.isdigit())


async def find_duplicate(user_id: str, email: str, phone: str) -> dict:
    """Return {is_duplicate, existing_row}. Dedup key: normalized email, fallback phone."""
    norm_email = _norm_email(email)
    norm_phone = _norm_phone(phone)

    async with _Session() as session:
        result = await session.execute(
            select(_Contact).where(_Contact.user_id == user_id)
        )
        rows = result.scalars().all()

    for row in rows:
        if norm_email and _norm_email(row.email or "") == norm_email:
            return {
                "is_duplicate": True,
                "existing_row": {"name": row.name, "email": row.email, "phone": row.phone, "company": row.company},
            }
        if norm_phone and _norm_phone(row.phone or "") == norm_phone:
            return {
                "is_duplicate": True,
                "existing_row": {"name": row.name, "email": row.email, "phone": row.phone, "company": row.company},
            }

    return {"is_duplicate": False, "existing_row": None}


async def insert_contact(user_id: str, contact: dict) -> str:
    """Insert a new contact row and return its UUID."""
    contact_id = str(uuid.uuid4())
    row = _Contact(
        id=contact_id,
        user_id=user_id,
        name=contact.get("name", ""),
        phone=str(contact.get("phone", "")),
        email=contact.get("email", ""),
        company=contact.get("company", ""),
        session_id=contact.get("session_id", ""),
        created_at=datetime.now(timezone.utc),
    )
    async with _Session() as session:
        session.add(row)
        await session.commit()
    return contact_id


async def update_audio(contact_id: str, audio_url: str, transcript: str) -> None:
    async with _Session() as session:
        await session.execute(
            update(_Contact)
            .where(_Contact.id == contact_id)
            .values(audio_url=audio_url, transcript=transcript)
        )
        await session.commit()


async def update_enrichment(contact_id: str, website: str, linkedin: str) -> None:
    async with _Session() as session:
        await session.execute(
            update(_Contact)
            .where(_Contact.id == contact_id)
            .values(website=website, linkedin=linkedin)
        )
        await session.commit()


async def get_contacts(user_id: str) -> list[dict]:
    async with _Session() as session:
        result = await session.execute(
            select(_Contact)
            .where(_Contact.user_id == user_id)
            .order_by(_Contact.created_at.desc())
        )
        rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "phone": r.phone,
            "email": r.email,
            "company": r.company,
            "website": r.website or "",
            "linkedin": r.linkedin or "",
            "audio_url": r.audio_url or "",
            "transcript": r.transcript or "",
            "session_id": r.session_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def export_contacts_csv(user_id: str) -> str:
    contacts = await get_contacts(user_id)
    output = io.StringIO()
    fieldnames = [
        "name", "phone", "email", "company", "website", "linkedin",
        "audio_url", "transcript", "session_id", "created_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for c in contacts:
        writer.writerow({k: c.get(k, "") or "" for k in fieldnames})
    return output.getvalue()
