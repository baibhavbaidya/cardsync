"""Resend transactional email — contact-logged notifications sent to the user."""

import logging
import os

import resend

resend.api_key = os.environ["RESEND_API_KEY"]

logger = logging.getLogger(__name__)

_FROM = "CardSync <noreply@cardsync.dev>"


def send_alert(name: str, company: str, phone: str, email: str, to_email: str) -> str:
    """Send a contact-logged notification to to_email. Returns 'sent' or 'failed'."""
    subject = f"New contact logged: {name} from {company}"
    html = f"""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:480px;color:#18181b;">
  <h2 style="margin:0 0 4px;">{name}</h2>
  <p style="margin:0 0 20px;color:#71717a;">{company}</p>
  <table style="border-collapse:collapse;width:100%;">
    <tr>
      <td style="padding:6px 0;color:#71717a;width:72px;font-size:13px;">Phone</td>
      <td style="padding:6px 0;font-size:13px;">{phone or "—"}</td>
    </tr>
    <tr>
      <td style="padding:6px 0;color:#71717a;font-size:13px;">Email</td>
      <td style="padding:6px 0;font-size:13px;">{email or "—"}</td>
    </tr>
  </table>
  <p style="margin-top:28px;font-size:12px;color:#a1a1aa;">Sent by CardSync</p>
</div>
""".strip()

    try:
        resend.Emails.send({"from": _FROM, "to": [to_email], "subject": subject, "html": html})
        return "sent"
    except Exception as exc:
        logger.warning("send_alert failed for %r: %s", to_email, exc)
        return "failed"
