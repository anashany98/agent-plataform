#!/usr/bin/env python3
"""Offline regression for backup v4 encryption, checksums and archive safety."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_backup_module():
    path = ROOT / "scripts/backup-restore-integral.py"
    spec = importlib.util.spec_from_file_location("backup_restore_integral", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("no se pudo cargar el motor backup")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    backup = load_backup_module()
    openssl = backup.find_executable("openssl")
    if not openssl:
        raise RuntimeError("openssl no está instalado")
    if shutil.which("openssl") is None:
        os.environ["PATH"] = str(Path(openssl).parent) + os.pathsep + os.environ.get("PATH", "")
    previous_passphrase = os.environ.get("BACKUP_ENCRYPTION_PASSPHRASE")
    os.environ["BACKUP_ENCRYPTION_PASSPHRASE"] = "backup-format-self-test-only-0123456789"
    try:
        with tempfile.TemporaryDirectory(prefix="backup-format-") as directory:
            root = Path(directory)
            stage = root / "stage"
            stage.mkdir()
            (stage / "deployment.env").write_text("COMPOSE_PROJECT_NAME=agent-self-test\n", encoding="utf-8")
            (stage / "release-manifest.json").write_text(
                '{"format_version":1,"release_version":"self-test"}\n', encoding="utf-8"
            )
            (stage / "bridge-db.dump").write_bytes(b"synthetic-pg-custom-dump")
            for name in ("bridge-uploads.tar", "bridge-automation-email.tar"):
                payload = root / f"{name}.txt"
                payload.write_text("safe", encoding="utf-8")
                with tarfile.open(stage / name, "w:") as archive:
                    archive.add(payload, arcname="safe.txt")
                backup.validate_volume_tar(stage / name)
            files = [
                "bridge-db.dump",
                "bridge-uploads.tar",
                "bridge-automation-email.tar",
                "deployment.env",
                "release-manifest.json",
            ]
            manifest = {
                "format_version": 4,
                "client_id": "self-test",
                "project": "agent-self-test",
                "profile": "production",
                "config_sha256": backup.sha256_file(stage / "deployment.env"),
                "files": list(files),
            }
            (stage / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            files.append("manifest.json")
            backup.write_checksums(stage, files)
            package = root / "package.tar.gz"
            with tarfile.open(package, "w:gz") as archive:
                for name in [*files, "SHA256SUMS"]:
                    archive.add(stage / name, arcname=name, recursive=False)
            encrypted = root / "self-test.tar.gz.enc"
            backup.run(
                [
                    "openssl",
                    "enc",
                    "-aes-256-cbc",
                    "-salt",
                    "-pbkdf2",
                    "-iter",
                    "200000",
                    "-pass",
                    "env:BACKUP_ENCRYPTION_PASSPHRASE",
                    "-in",
                    str(package),
                    "-out",
                    str(encrypted),
                ],
                capture=False,
            )
            encrypted.with_suffix(encrypted.suffix + ".sha256").write_text(
                f"{backup.sha256_file(encrypted)}  {encrypted.name}\n", encoding="ascii"
            )
            backup.write_authentication(encrypted)
            extract = root / "extract"
            extract.mkdir()
            restored_manifest = backup.decrypt_and_extract(encrypted, extract)
            if restored_manifest != manifest:
                raise RuntimeError("el manifiesto restaurado no coincide")
            tampered = root / "tampered.tar.gz.enc"
            data = bytearray(encrypted.read_bytes())
            data[-1] ^= 1
            tampered.write_bytes(data)
            tampered.with_suffix(tampered.suffix + ".sha256").write_text(
                f"{backup.sha256_file(encrypted)}  {tampered.name}\n", encoding="ascii"
            )
            shutil.copy2(backup.authentication_path(encrypted), backup.authentication_path(tampered))
            tamper_extract = root / "tamper-extract"
            tamper_extract.mkdir()
            try:
                backup.decrypt_and_extract(tampered, tamper_extract)
            except RuntimeError as exc:
                if "autenticación HMAC" not in str(exc):
                    raise
            else:
                raise RuntimeError("un backup alterado pasó la verificación")
            try:
                backup.normalized_member("../escape")
            except RuntimeError:
                pass
            else:
                raise RuntimeError("se aceptó path traversal en archive")
    finally:
        if previous_passphrase is None:
            os.environ.pop("BACKUP_ENCRYPTION_PASSPHRASE", None)
        else:
            os.environ["BACKUP_ENCRYPTION_PASSPHRASE"] = previous_passphrase
    print(
        "backup_format=PASS v4 aes256_pbkdf2 hmac checksums traversal_rejected "
        "automation_volume release_manifest"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, tarfile.TarError, ValueError) as exc:
        print(f"backup_format=FAIL {exc}")
        raise SystemExit(1) from exc
