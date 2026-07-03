"""Pydantic models for requests, responses, and the contact schema."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class Contact(BaseModel):
    name: str
    phone: str
    email: str
    company: str
    website: Optional[str] = None
    linkedin: Optional[str] = None


class SessionCreate(BaseModel):
    title: Optional[str] = "New session"


class SessionUpdate(BaseModel):
    title: str


class SessionOut(BaseModel):
    session_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    session_id: str
    role: Literal["user", "assistant"]
    type: Literal["text", "image", "audio"]
    content: Optional[str] = None
    media_url: Optional[str] = None
    created_at: datetime


class UploadOut(BaseModel):
    key: str
    kind: Literal["image", "audio"]


class UserSetupRequest(BaseModel):
    email: str


class UserSetupOut(BaseModel):
    scan_count: int
    notification_email: str


class WaitlistRequest(BaseModel):
    email: str


class WaitlistOut(BaseModel):
    status: str


class ContactOut(BaseModel):
    id: str
    name: str
    phone: str
    email: str
    company: str
    website: Optional[str] = None
    linkedin: Optional[str] = None
    audio_url: Optional[str] = None
    transcript: Optional[str] = None
    session_id: str
    created_at: Optional[str] = None
