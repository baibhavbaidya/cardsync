"""Meta WhatsApp Cloud API. Sends a utility template alert to the manager."""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_TOKEN = os.environ.get("WHATSAPP_TOKEN")
_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
_RECIPIENT = os.environ.get("WHATSAPP_RECIPIENT")
_TEMPLATE = os.environ.get("WHATSAPP_TEMPLATE_NAME", "new_card_logged")


def send_alert(name: str, company: str) -> str:
    """POST a template message to the Meta Graph API.

    Uses hello_world (no params) when WHATSAPP_TEMPLATE_NAME=hello_world,
    otherwise sends name and company as body parameters to the custom template.
    Returns "sent" on success or an error string on failure.
    """
    template: dict = {
        "name": _TEMPLATE,
        "language": {"code": "en_US"},
    }
    if _TEMPLATE != "hello_world":
        template["components"] = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": name},
                    {"type": "text", "text": company},
                ],
            }
        ]

    payload = {
        "messaging_product": "whatsapp",
        "to": _RECIPIENT,
        "type": "template",
        "template": template,
    }

    with httpx.Client() as client:
        response = client.post(
            f"https://graph.facebook.com/v21.0/{_PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {_TOKEN}", "Content-Type": "application/json"},
            json=payload,
        )

    if response.is_success:
        logger.info("WhatsApp alert sent (status %s)", response.status_code)
        return "sent"
    logger.error(
        "WhatsApp API error — status: %s, body: %s",
        response.status_code,
        response.text,
    )
    return f"error {response.status_code}: {response.text}"
