"""Evals D-009: preflight de puertos en el aprovisionamiento.

El aprovisionamiento debe validar ANTES de escribir ``.env``/build/up que el
puerto proxy está libre, para no alterar instalaciones existentes ni dejar
artefactos parciales. ``port_in_use`` se prueba de forma hermética (sin Docker):
se extrae la función del script y se evalúa contra un puerto ocupado y uno libre.
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "provision-client.sh"

# /dev/tcp es fiable en bash de Linux/macOS; en el bash de Windows (MSYS2) la
# ruta /dev/tcp se transforma y no conecta. Estas pruebas corren donde /dev/tcp
# funciona; en Windows el preflight equivalente lo da provision-client.ps1.
_linux_only = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="/dev/tcp no es fiable en bash de Windows; el preflight Windows lo cubre el .ps1",
)


def _extract_port_in_use() -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("port_in_use()")
    # La función termina en la primera línea que es solo "}".
    end = text.index("\n}", start)
    return text[start:end + 2]


def _probe(port: int) -> str:
    fn = _extract_port_in_use()
    proc = subprocess.run(
        ["bash", "-c", f"{fn}\nif port_in_use {port}; then echo INUSE; else echo FREE; fi"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.stdout.strip()


@_linux_only
def test_port_in_use_detects_occupied_port() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        assert _probe(port) == "INUSE", "Debe detectar un puerto ocupado"
    finally:
        listener.close()


@_linux_only
def test_port_in_use_reports_free_port() -> None:
    # Reserva y libera un puerto para obtener uno libre.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    assert _probe(port) == "FREE", "Debe reportar libre un puerto sin listener"


@_linux_only
def test_provision_script_syntax_is_valid() -> None:
    # bash -n desde Python nativo de Windows cuelga (MSYS2 no cierra sus pipes
    # de consola); en Windows el preflight equivalente lo cubre el .ps1.
    proc = subprocess.run(
        ["bash", "-n", "scripts/provision-client.sh"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO),
    )
    assert proc.returncode == 0, f"bash -n falló: {proc.stderr}"
