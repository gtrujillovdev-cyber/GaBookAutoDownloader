import os
import socket
import smtplib
import logging
from email.message import EmailMessage
from typing import Optional
from gabook.config import (
    GMAIL_USER,
    GMAIL_APP_PASSWORD,
    DEFAULT_KINDLE_EMAIL,
    SMTP_TIMEOUT,
    MAX_ATTACHMENT_BYTES
)

logger = logging.getLogger(__name__)

def send_to_kindle(filepath: str, book_title: Optional[str] = None, recipient_email: Optional[str] = None) -> bool:
    """
    Sends an EPUB file to the specified Kindle email address via Gmail SMTP.
    If recipient_email is not specified, falls back to default KINDLE_EMAIL.
    """
    target_email = recipient_email or DEFAULT_KINDLE_EMAIL

    if not os.path.exists(filepath):
        logger.error(f"File not found: {filepath}")
        return False

    file_size = os.path.getsize(filepath)
    if file_size > MAX_ATTACHMENT_BYTES:
        logger.error(f"File {filepath} ({file_size / (1024*1024):.1f} MB) exceeds maximum allowed email size.")
        return False

    if not GMAIL_USER or not GMAIL_APP_PASSWORD or not target_email:
        logger.error("Missing email configuration or recipient email.")
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

    msg = EmailMessage()
    msg["From"] = GMAIL_USER
    msg["To"] = target_email

    if is_kindle_target:
        msg["Subject"] = subject
        msg.set_content(f"Enviando documento personal a Kindle: {subject}")
    else:
        msg["Subject"] = f"📚 Tu libro: {subject}"
        msg.set_content(
            f"¡Hola!\n\nAdjuntamos tu libro '{subject}' en formato EPUB listo para disfrutar.\n\n"
            "Saludos,\nTu asistente GaBookAutoDownloader 📖"
        )

    with open(filepath, "rb") as f:
        file_data = f.read()

    msg.add_attachment(
        file_data,
        maintype="application",
        subtype="epub+zip",
        filename=clean_display_name
    )

    def _smtp_send(host: str, port: int, use_ssl: bool) -> None:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT) as srv:
                srv.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                srv.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT) as srv:
                srv.ehlo()
                srv.starttls()
                srv.ehlo()
                srv.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                srv.send_message(msg)

    # Resolve smtp.gmail.com to IPv4 explicitly to avoid Render's IPv6 routing issues
    try:
        ipv4 = socket.getaddrinfo("smtp.gmail.com", None, socket.AF_INET)[0][4][0]
    except Exception:
        ipv4 = "smtp.gmail.com"

    last_error: Exception = Exception("No attempt made")
    for host, port, use_ssl in [
        (ipv4, 587, False),   # STARTTLS IPv4 (Render-friendly)
        ("smtp.gmail.com", 587, False),  # STARTTLS fallback
        (ipv4, 465, True),    # SSL IPv4
        ("smtp.gmail.com", 465, True),   # SSL fallback
    ]:
        try:
            logger.info(f"Connecting to Gmail SMTP for {GMAIL_USER} -> {target_email} ({host}:{port})...")
            _smtp_send(host, port, use_ssl)
            logger.info(f"✅ Successfully sent '{clean_display_name}' to {target_email}")
            return True
        except Exception as e:
            logger.warning(f"SMTP attempt {host}:{port} failed: {e}")
            last_error = e

    logger.error(f"❌ Failed to send email via SMTP: {last_error}")
    return False
