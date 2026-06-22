"""Google Sheets as the contact database, via gspread.

Columns (1-based):
  1:Name | 2:Phone | 3:Email | 4:Company | 5:Website | 6:LinkedIn | 7:Audio URL | 8:Transcript | 9:Session ID | 10:Created At
"""

import base64
import json
import os
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _client() -> gspread.Client:
    raw = base64.b64decode(os.environ["GOOGLE_SERVICE_ACCOUNT_B64"])
    creds = Credentials.from_service_account_info(json.loads(raw), scopes=_SCOPES)
    return gspread.authorize(creds)


def _sheet() -> gspread.Worksheet:
    return _client().open_by_key(os.environ["GOOGLE_SHEET_ID"]).sheet1


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _norm_phone(phone) -> str:
    return "".join(ch for ch in (str(phone) if phone else "") if ch.isdigit())


def find_duplicate(email: str, phone: str) -> dict:
    """Return {"is_duplicate": bool, "existing_row": dict | None}.

    Dedup key: normalized email if present, else normalized phone.
    """
    rows = _sheet().get_all_records()
    norm_email = _norm_email(email)
    norm_phone = _norm_phone(phone)

    for row in rows:
        if norm_email:
            if _norm_email(row.get("Email", "")) == norm_email:
                return {"is_duplicate": True, "existing_row": dict(row)}
        elif norm_phone:
            if _norm_phone(row.get("Phone", "")) == norm_phone:
                return {"is_duplicate": True, "existing_row": dict(row)}

    return {"is_duplicate": False, "existing_row": None}


def append_contact(contact: dict) -> str:
    """Append a row and return its row number as the row_id."""
    ws = _sheet()
    row = [
        contact.get("name", ""),
        str(contact.get("phone", "")),  # force string so Sheets doesn't coerce to int
        contact.get("email", ""),
        contact.get("company", ""),
        "",  # Website
        "",  # LinkedIn
        "",  # Audio URL
        "",  # Transcript
        contact.get("session_id", ""),
        datetime.now(timezone.utc).isoformat(),
    ]
    ws.append_row(row, value_input_option="RAW")
    # Header is row 1, so total rows after append == the new row's number.
    row_id = str(len(ws.get_all_values()))
    return row_id


def update_audio(row_id: str, audio_url: str, transcript: str) -> None:
    """Write Audio URL (col G/7) and Transcript (col H/8) for an existing row."""
    ws = _sheet()
    row_num = int(row_id)
    ws.update([[audio_url, transcript]], f"G{row_num}:H{row_num}")


def update_enrichment(row_id: str, website: str, linkedin: str) -> None:
    """Write Website (col E/5) and LinkedIn (col F/6) for an existing row."""
    ws = _sheet()
    row_num = int(row_id)
    ws.update([[website, linkedin]], f"E{row_num}:F{row_num}")
