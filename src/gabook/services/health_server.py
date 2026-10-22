import os
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

logger = logging.getLogger(__name__)

class HealthCheckHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler to satisfy cloud health checks (Render, Koyeb, Fly.io)."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        payload = {
            "status": "healthy",
            "service": "GaBookAutoDownloader",
            "version": "2.0"
        }
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress periodic health-check access logs to keep log streams clean
        pass

def start_health_server(port: Optional[int] = None) -> Optional[HTTPServer]:
    """
    Starts the HTTP health check server in a background daemon thread.
    If no port is specified and PORT environment variable is missing, returns None.
    """
    target_port = port or (int(os.environ["PORT"]) if "PORT" in os.environ and os.environ["PORT"].isdigit() else None)
    if not target_port:
        return None

    try:
        server = HTTPServer(("0.0.0.0", target_port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True, name="HealthCheckServerThread")
        thread.start()
        logger.info(f"🌐 Health check HTTP server activo en http://0.0.0.0:{target_port}/health")
        return server
    except Exception as e:
        logger.warning(f"No se pudo iniciar el servidor de salud HTTP en puerto {target_port}: {e}")
        return None
