import os
import re
import time
import html
import logging
import imaplib
import email
from email.header import decode_header
import requests
from bs4 import BeautifulSoup
from email.utils import parseaddr
from urllib.parse import urlparse
from typing import Dict, Optional
from gabook.config import GMAIL_USER, GMAIL_APP_PASSWORD, IMAP_TIMEOUT

logger = logging.getLogger(__name__)

_AMAZON_HOST_RE = re.compile(
    r"(^|\.)amazon\.(com|es|co\.uk|de|fr|it|nl|pl|se|ca|com\.mx|com\.br|co\.jp|in|com\.au)$"
)

def _is_amazon_sender(from_header: str) -> bool:
    """True if the From address belongs to an Amazon domain (header-level check)."""
    addr = parseaddr(from_header or "")[1].lower()
    domain = addr.rsplit("@", 1)[-1] if "@" in addr else ""
    return bool(_AMAZON_HOST_RE.search(domain))

def _is_trusted_amazon_url(url: str) -> bool:
    """Only https links on Amazon domains may be opened automatically."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(_AMAZON_HOST_RE.search((parsed.hostname or "").lower()))

def clean_subject(raw_subject: str) -> str:
    """Decodes email subject headers."""
    decoded_fragments = decode_header(raw_subject)
    subject_parts = []
    for fragment, encoding in decoded_fragments:
        if isinstance(fragment, bytes):
            subject_parts.append(fragment.decode(encoding or "utf-8", errors="ignore"))
        else:
            subject_parts.append(str(fragment))
    return "".join(subject_parts)

def extract_email_body(msg) -> str:
    """Extracts plain text or html content from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type in ["text/plain", "text/html"]:
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode("utf-8", errors="ignore") + "\n"
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="ignore")
    return body

def verify_amazon_link(url: str) -> bool:
    """Visits the Amazon verification link to confirm the Kindle document."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    clean_url = html.unescape(url.strip())
    if not _is_trusted_amazon_url(clean_url):
        logger.warning("Refusing to open non-Amazon verification link.")
        return False
    try:
        resp = requests.get(clean_url, headers=headers, timeout=15, allow_redirects=True)
        logger.info(f"Amazon verification request status: {resp.status_code}")
        return resp.status_code < 400
    except Exception as e:
        logger.error(f"Error clicking Amazon verification link: {e}")
        return False

def monitor_kindle_delivery(timeout_seconds: int = 75, poll_interval: int = 5) -> Dict:
    """
    Monitors Gmail INBOX for notifications from Amazon / Kindle reusing a single IMAP connection.
    - If verification request email arrives, clicks the link automatically.
    - If error email arrives, reports failure.
    - If timeout expires with no error, reports silent success.
    """
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        return {"status": "error", "message": "Credenciales de Gmail no configuradas."}

    start_time = time.time()
    seen_message_ids = set()
    mail = None

    def connect_imap():
        m = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=IMAP_TIMEOUT)
        m.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        m.select("INBOX")
        return m

    # Pre-scan existing unread message ids to avoid reacting to older emails
    try:
        mail = connect_imap()
        status, data = mail.search(None, '(FROM "amazon")')
        if status == "OK" and data[0]:
            seen_message_ids = set(data[0].split())
    except Exception as e:
        logger.warning(f"Initial IMAP check warning: {e}")

    logger.info(f"Starting Gmail monitoring for Kindle delivery (Timeout: {timeout_seconds}s)...")

    try:
        while (time.time() - start_time) < timeout_seconds:
            time.sleep(poll_interval)
            try:
                if not mail:
                    mail = connect_imap()

                mail.noop()
                status, data = mail.search(None, '(FROM "amazon")')
                if status != "OK" or not data[0]:
                    continue

                current_ids = set(data[0].split())
                new_ids = current_ids - seen_message_ids

                for msg_id in new_ids:
                    status, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if status != "OK" or not msg_data or not msg_data[0]:
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    subject = clean_subject(msg.get("Subject", ""))
                    from_header = msg.get("From", "").lower()
                    body = extract_email_body(msg)

                    if not _is_amazon_sender(from_header):
                        logger.warning(f"Ignoring email with non-Amazon sender: {from_header!r}")
                        continue

                    logger.info(f"📬 Correo de Amazon detectado: '{subject}' de {from_header}")

                    # Check if it's a verification request
                    is_verification = (
                        any(kw in subject.lower() for kw in ["verifi", "solicitud", "kindle document", "verify", "send to kindle"]) or
                        any(kw in body.lower() for kw in ["verificar solicitud", "verify request", "verificar tu documento", "haz clic en el enlace"])
                    )

                    if is_verification:
                        verify_url = None
                        soup = BeautifulSoup(body, "html.parser")
                        for a in soup.find_all("a", href=True):
                            href = a["href"]
                            text = a.get_text(strip=True).lower()
                            if any(k in href.lower() for k in ["verification", "confirm", "verify", "sendtokindle"]) or \
                               any(k in text for k in ["verificar", "verify"]):
                                verify_url = href
                                break

                        if not verify_url:
                            matches = re.findall(r'https://[^\s<>"]+(?:sendtokindle|verification|confirm|verify|gp/f\.html)[^\s<>"]*', body)
                            if matches:
                                verify_url = matches[0]

                        if verify_url and not _is_trusted_amazon_url(html.unescape(verify_url.strip())):
                            logger.warning("Verification link is not on an Amazon domain; ignoring it.")
                            verify_url = None

                        if verify_url:
                            verify_url = html.unescape(verify_url.strip())
                            logger.info(f"🔗 Enlace de verificación encontrado: {verify_url}")
                            success = verify_amazon_link(verify_url)
                            if success:
                                return {
                                    "status": "verified_auto",
                                    "message": "Amazon envió correo de verificación y el bot lo aprobó automáticamente ✅"
                                }
                            else:
                                return {
                                    "status": "needs_manual_click",
                                    "message": f"Amazon envió verificación: {verify_url}"
                                }

                    # Check if it's an error notification
                    is_error = any(kw in subject.lower() for kw in ["problema", "problem", "error", "no se ha podido entregar", "rejected"])
                    if is_error:
                        return {
                            "status": "rejected",
                            "message": f"Amazon rechazó el documento: {subject}"
                        }

            except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError) as imap_err:
                logger.warning(f"IMAP temporary connection error: {imap_err}. Reconnecting...")
                if mail:
                    try:
                        mail.logout()
                    except Exception:
                        pass
                mail = None
            except Exception as e:
                logger.error(f"Error checking Gmail IMAP: {e}")

    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass

    # If timeout passed with no error emails
    return {
        "status": "delivered_silent",
        "message": "Enviado con éxito a Amazon (entrega directa al Kindle)."
    }
