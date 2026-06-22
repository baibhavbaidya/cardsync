"""OpenAI: gpt-4o vision extraction and Whisper transcription."""

import base64
import io
import os

from openai import OpenAI
from pydantic import BaseModel

from app.services import storage

_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

_MIME = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}


class _CardFields(BaseModel):
    name: str
    phone: str
    email: str
    company: str


class _CompanyInfo(BaseModel):
    website: str  # empty string if not found or uncertain
    linkedin: str  # empty string if not found or uncertain


def extract_card(image_key: str) -> dict:
    """Download the card from R2 and extract Name, Phone, Email, Company with gpt-4o vision."""
    image_bytes = storage.get_bytes(image_key)
    b64 = base64.b64encode(image_bytes).decode()
    ext = image_key.rsplit(".", 1)[-1].lower() if "." in image_key else "jpeg"
    mime = f"image/{_MIME.get(ext, 'jpeg')}"

    response = _client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a card digitization assistant. Extract contact details from the "
                    "visiting card image. Return an empty string for any field not visible."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": "Extract the contact details from this visiting card."},
                ],
            },
        ],
        response_format=_CardFields,
    )

    card = response.choices[0].message.parsed
    return {"name": card.name, "phone": card.phone, "email": card.email, "company": card.company}


def enrich_company(company: str) -> dict:
    """Use gpt-4o's knowledge to find a company's website and LinkedIn URL."""
    response = _client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a company research assistant. Given a company name, return its "
                    "official website URL and LinkedIn company page URL. "
                    "Return an empty string for any URL you are not confident about. "
                    "Do not guess or fabricate URLs."
                ),
            },
            {
                "role": "user",
                "content": f"Find the website and LinkedIn URL for: {company}",
            },
        ],
        response_format=_CompanyInfo,
    )
    info = response.choices[0].message.parsed
    return {"website": info.website, "linkedin": info.linkedin}


def transcribe(audio_key: str) -> str:
    """Transcribe a voice note with Whisper."""
    audio_bytes = storage.get_bytes(audio_key)
    buf = io.BytesIO(audio_bytes)
    buf.name = audio_key.split("/")[-1]
    response = _client.audio.transcriptions.create(model="whisper-1", file=buf)
    return response.text
