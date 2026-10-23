import os
import base64
import logging
import requests
from typing import Optional
from gabook.config import (
    GMAIL_USER,
    DEFAULT_KINDLE_EMAIL,
    MAX_ATTACHMENT_BYTES
)

logger = logging.getLogger(__name__)

_MAILJET_API_KEY = os.getenv("MAILJET_API_KEY")
_MAILJET_SECRET_KEY = os.getenv("MAILJET_SECRET_KEY")
_MAILJET_URL = "https://api.mailjet.com/v3.1/send"


def send_to_kindle(filepath: str, book_title: Optional[str] = None, recipient_email: Optional[str] = None) -> bool:
    """
    Sends an EPUB file to the specified Kindle email address via Mailjet REST API.
    Uses HTTPS (port 443) — compatible with Render free tier (SMTP ports are blocked).
    """
    target_email = recipient_email or DEFAULT_KINDLE_EMAIL

    if not os.path.exists(filepath):
        logger.error(f"File not found: {filepath}")
        return False

    file_size = os.path.getsize(filepath)
    if file_size > MAX_ATTACHMENT_BYTES:
        logger.error(f"File {filepath} ({file_size / (1024*1024):.1f} MB) exceeds maximum allowed email size.")
        return False

    if not GMAIL_USER or not target_email:
        logger.error("Missing sender or recipient email.")
        return False

    if not _MAILJET_API_KEY or not _MAILJET_SECRET_KEY:
        logger.error("Missing MAILJET_API_KEY or MAILJET_SECRET_KEY environment variables.")
        return False

    filename = os.path.basename(filepath)
    # Strip any internal random suffix like _a1b2c3 for the Kindle reader presentation
    clean_display_name = filename
    if "_" in filename and filename.endswith(".epub"):
        base_part = filename[:-5]
        parts = base_part.rsplit("_", 1)
        if len(parts) == 2 and len(parts[1]) == 6:
            clean_display_name = f"{parts[0]}.epub"

    subject = book_title if book_title else clean_display_name
    is_kindle_target = target_email.lower().endswith("@kindle.com")

    with open(filepath, "rb") as f:
        file_b64 = base64.b64encode(f.read()).decode()

    if is_kindle_target:
        email_subject = subject
        text_body = f"Enviando documento personal a Kindle: {subject}"
    else:
        email_subject = f"Tu libro: {subject}"
        text_body = (
            f"Hola!\n\nAdjuntamos tu libro '{subject}' en formato EPUB listo para disfrutar.\n\n"
            "Saludos,\nTu asistente GaBookAutoDownloader"
        )

    payload = {
        "Messages": [
            {
                "From": {"Email": GMAIL_USER, "Name": "GaBook"},
                "To": [{"Email": target_email}],
                "Subject": email_subject,
                "TextPart": text_body,
                "Attachments": [
                    {
                        "ContentType": "application/epub+zip",
                        "Filename": clean_display_name,
                        "Base64Content": file_b64,
                    }
                ],
            }
        ]
    }

    try:
        logger.info(f"Sending via Mailjet: {GMAIL_USER} -> {target_email}")
        resp = requests.post(
            _MAILJET_URL,
            auth=(_MAILJET_API_KEY, _MAILJET_SECRET_KEY),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        logger.info(f"Successfully sent '{clean_display_name}' to {target_email}")
        return True
    except Exception as e:
        logger.error(f"Mailjet send failed: {e}")
        return False
