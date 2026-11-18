#!/usr/bin/env python3
"""
diagnose_kindle.py — Diagnóstico completo de entrega Kindle para un destinatario.

Uso:
    python scripts/diagnose_kindle.py              # usa KINDLE_EMAIL_GONZALO del .env
    python scripts/diagnose_kindle.py otro@kindle.com

Qué hace:
  1. Comprueba que todas las variables de entorno necesarias están configuradas.
  2. Genera un EPUB mínimo válido en memoria.
  3. Lo envía vía Mailjet y captura el MessageID.
  4. Consulta la API de Mailjet para ver el estado real de entrega
     (sent, delivered, bounced, spam, blocked…).
  5. Imprime un informe con la causa exacta del fallo si la hay.
"""

import os
import sys
import time
import base64
import zipfile
import io
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

# --- Cargar .env del raíz del proyecto ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

# ── Variables de entorno ───────────────────────────────────────────────────────
MAILJET_API_KEY    = os.getenv("MAILJET_API_KEY")
MAILJET_SECRET_KEY = os.getenv("MAILJET_SECRET_KEY")
GMAIL_USER         = os.getenv("GMAIL_USER")
TARGET_EMAIL       = sys.argv[1] if len(sys.argv) > 1 else os.getenv("KINDLE_EMAIL_GONZALO")

MAILJET_SEND_URL   = "https://api.mailjet.com/v3.1/send"
MAILJET_MSG_URL    = "https://api.mailjet.com/v3/REST/message"
MAILJET_HIST_URL   = "https://api.mailjet.com/v3/REST/messagehistory/{message_id}"

SEP = "─" * 60


def check(label: str, value, hint: str = ""):
    ok = bool(value) and value not in ("familiar1@kindle.com", "familiar2@kindle.com",
                                        "gabook.sender@gmail.com", "tu_kindle@kindle.com")
    status = "✅" if ok else "❌"
    print(f"  {status}  {label}: {value or '(no configurado)'}")
    if not ok and hint:
        print(f"       → {hint}")
    return ok


def build_minimal_epub() -> bytes:
    """Crea un EPUB válido mínimo en memoria (no necesita Calibre ni dependencias)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype DEBE ir sin comprimir y primero
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", """\
<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""")
        zf.writestr("OEBPS/content.opf", """\
<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">gabook-diagnostic-test</dc:identifier>
    <dc:title>GaBook Diagnostic Test</dc:title>
    <dc:language>es</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine><itemref idref="nav"/></spine>
</package>""")
        zf.writestr("OEBPS/nav.xhtml", """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Test</title></head>
<body>
  <nav epub:type="toc"><ol><li><a href="#">Test GaBook</a></li></ol></nav>
  <p>Este es un EPUB de diagnóstico enviado por GaBookAutoDownloader.</p>
</body>
</html>""")
    return buf.getvalue()


def send_test_epub(target_email: str) -> dict | None:
    """Envía el EPUB de prueba y devuelve la respuesta completa de Mailjet."""
    epub_bytes = build_minimal_epub()
    epub_b64   = base64.b64encode(epub_bytes).decode()

    payload = {
        "Messages": [{
            "From":    {"Email": GMAIL_USER, "Name": "GaBook Diagnóstico"},
            "To":      [{"Email": target_email}],
            "Subject": "GaBook Diagnostic Test",
            "TextPart": "Test de diagnóstico GaBook.",
            "Attachments": [{
                "ContentType": "application/epub+zip",
                "Filename":    "gabook_test.epub",
                "Base64Content": epub_b64,
            }],
        }]
    }

    try:
        resp = requests.post(
            MAILJET_SEND_URL,
            auth=(MAILJET_API_KEY, MAILJET_SECRET_KEY),
            json=payload,
            timeout=30,
        )
        return resp.json() if resp.headers.get("Content-Type", "").startswith("application/json") else None
    except Exception as e:
        print(f"\n  ❌ Error de red al conectar con Mailjet: {e}")
        return None


def get_message_status(message_id: int) -> list[dict]:
    """Consulta el historial de eventos de un mensaje Mailjet."""
    try:
        url = MAILJET_HIST_URL.format(message_id=message_id)
        resp = requests.get(url, auth=(MAILJET_API_KEY, MAILJET_SECRET_KEY), timeout=15)
        data = resp.json()
        return data.get("Data", [])
    except Exception:
        return []


def interpret_status(events: list[dict]) -> str:
    """Traduce los eventos de Mailjet a lenguaje natural."""
    if not events:
        return "Sin eventos aún (puede tardar 10-30 seg en procesarse)"

    # Los eventos vienen ordenados del más antiguo al más nuevo
    latest = events[-1].get("EventType", "unknown") if events else "unknown"

    descriptions = {
        "sent":      "✅ Mailjet lo envió al servidor de Amazon",
        "delivered": "✅✅ Amazon CONFIRMÓ la recepción (debería aparecer en Docs del Kindle)",
        "open":      "✅ El email fue abierto",
        "bounce":    "❌ REBOTE — Amazon rechazó el email",
        "blocked":   "❌ BLOQUEADO por Mailjet (reputación o configuración)",
        "spam":      "⚠️  Marcado como spam por Amazon",
        "unsub":     "⚠️  El destinatario se ha dado de baja",
        "hardbounce":"❌ REBOTE PERMANENTE — el email Kindle no existe o es incorrecto",
        "softbounce":"⚠️  Rebote temporal — Amazon no respondió. Reintenta más tarde",
    }

    lines = []
    for ev in events:
        etype = ev.get("EventType", "?")
        ts    = ev.get("EventAt", "")
        desc  = descriptions.get(etype, f"Evento desconocido: {etype}")
        lines.append(f"    [{ts}] {desc}")

    return "\n".join(lines)


# ── DIAGNÓSTICO PRINCIPAL ──────────────────────────────────────────────────────

def main():
    print(f"\n{SEP}")
    print("  GaBook — Diagnóstico de entrega Kindle")
    print(SEP)

    print("\n[1] Verificando variables de entorno:")
    all_ok = True
    all_ok &= check("MAILJET_API_KEY",    MAILJET_API_KEY,
                    "Copia la API Key de mailjet.com → Account → API Keys")
    all_ok &= check("MAILJET_SECRET_KEY", MAILJET_SECRET_KEY,
                    "Copia la Secret Key del mismo sitio")
    all_ok &= check("GMAIL_USER (remitente)", GMAIL_USER,
                    "Pon el email real del remitente configurado en Mailjet como Sender")
    all_ok &= check("Email destino (hermano)", TARGET_EMAIL,
                    "Comprueba KINDLE_EMAIL_GONZALO en .env o pásalo como argumento")

    if not all_ok:
        print(f"\n{SEP}")
        print("  ❌ Hay variables sin configurar. Corrígelas en .env y vuelve a ejecutar.")
        print(SEP)
        sys.exit(1)

    print(f"\n  Destino: {TARGET_EMAIL}")
    is_kindle = TARGET_EMAIL.lower().endswith("@kindle.com")
    if not is_kindle:
        print("  ⚠️  El email no termina en @kindle.com — se enviará como email normal, no Send to Kindle")

    print(f"\n{SEP}")
    print("[2] Enviando EPUB de prueba vía Mailjet…")
    result = send_test_epub(TARGET_EMAIL)

    if result is None:
        print("  ❌ No se recibió respuesta de Mailjet. Comprueba las credenciales y la red.")
        sys.exit(1)

    messages = result.get("Messages", [])
    if not messages:
        print(f"  ❌ Respuesta inesperada de Mailjet:\n  {json.dumps(result, indent=2)}")
        sys.exit(1)

    msg      = messages[0]
    status   = msg.get("Status", "unknown")
    errors   = msg.get("Errors", [])

    if status != "success":
        print(f"  ❌ Mailjet devolvió status '{status}'")
        for err in errors:
            print(f"     Error {err.get('ErrorCode')}: {err.get('ErrorMessage')}")
            print(f"     Identificador: {err.get('ErrorIdentifier')}")
        sys.exit(1)

    to_list    = msg.get("To", [])
    message_id = to_list[0].get("MessageID") if to_list else None
    print(f"  ✅ Mailjet aceptó el mensaje. MessageID: {message_id}")

    print(f"\n{SEP}")
    print("[3] Esperando 15 segundos para que Mailjet procese la entrega…")
    for i in range(15, 0, -5):
        print(f"  {i}s…", end=" ", flush=True)
        time.sleep(5)
    print()

    print(f"\n{SEP}")
    print("[4] Consultando estado de entrega en Mailjet:")
    if message_id:
        events = get_message_status(message_id)
        print(interpret_status(events))
    else:
        print("  ⚠️  No se pudo obtener el MessageID, no se puede consultar el estado.")

    print(f"\n{SEP}")
    print("[5] Conclusión:")

    if not is_kindle:
        print("  ℹ️  El email no es @kindle.com — para probar Send to Kindle usa el email correcto.")
    else:
        print("""
  Si el estado es 'delivered':
    → El libro ESTÁ en el Kindle de tu hermano.
      Dile que abra: Biblioteca → filtro 'Documentos' (no 'Libros').

  Si el estado es 'sent' pero no 'delivered' tras varios minutos:
    → Amazon recibió el email pero no lo aceptó.
      Causa más probable: el remitente NO está en la lista blanca de su cuenta Amazon.
      Solución: que vaya a amazon.es → Cuenta → Gestionar contenido → Preferencias
               → Configuración de documentos personales → añadir: {remitente}

  Si el estado es 'bounce' o 'hardbounce':
    → El email Kindle está mal escrito en KINDLE_EMAIL_GONZALO del .env.
      Verifica en su Kindle: Ajustes → Mi cuenta → Email del dispositivo.

  Si aparece 'blocked':
    → Mailjet bloqueó el envío por reputación del dominio.
      Comprueba en mailjet.com → Sender Domains que el dominio esté verificado.
""".format(remitente=GMAIL_USER))

    print(SEP)


if __name__ == "__main__":
    main()
