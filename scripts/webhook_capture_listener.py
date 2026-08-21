"""Listener HTTP local para validación en vivo de webhooks salientes.

Imprime el método, las cabeceras y el cuerpo de cada POST recibido (para
verificar la firma X-Bridge-Webhook-Signature) y responde 200. Uso SOLO en
validación local contra el stack candidato; nunca en producción.

    python scripts/webhook_capture_listener.py [puerto]
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8123


class CaptureHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 — nombre de la stdlib
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        print("=" * 60, flush=True)
        print(f"POST {self.path}", flush=True)
        for key, value in self.headers.items():
            print(f"  {key}: {value}", flush=True)
        print("BODY:", flush=True)
        try:
            parsed = json.loads(body)
            print(json.dumps(parsed, indent=2, ensure_ascii=False), flush=True)
        except Exception:  # noqa: BLE001
            print(body.decode("utf-8", "replace"), flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"received": true}')

    def log_message(self, *args) -> None:  # noqa: ANN002 — silenciar el log
        pass


if __name__ == "__main__":
    print(f"Escuchando en 127.0.0.1:{PORT}…", flush=True)
    HTTPServer(("127.0.0.1", PORT), CaptureHandler).serve_forever()
