#!/usr/bin/env python3
"""Encrypted, checksummed backup/restore for an isolated client deployment."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
HELPER_IMAGE = (
    "nginx:1.30.4-alpine3.24@"
    "sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46"
)
AUTH_ITERATIONS = 200_000
ALLOWED_PACKAGE_FILES = {
    "bridge-db.dump",
    "chatwoot-db.dump",
    "activepieces-db.dump",
    "bridge-uploads.tar",
    "bridge-automation-email.tar",
    "chatwoot-storage.tar",
    "activepieces-cache.tar",
    "deployment.env",
    "release-manifest.json",
    "manifest.json",
    "SHA256SUMS",
}


def find_executable(name: str) -> str | None:
    found = shutil.which(name)
    if found or os.name != "nt":
        return found
    for candidate in (
        Path("C:/Program Files/Git/usr/bin") / f"{name}.exe",
        Path("C:/Program Files/Git/mingw64/bin") / f"{name}.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def run(command: list[str], *, capture: bool = True) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "sin detalle").strip().splitlines()[-1]
        raise RuntimeError(f"falló {' '.join(command[:3])}: {detail}")
    return (completed.stdout or "").strip()


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hmac_sha256_file(path: Path, key: bytes) -> str:
    digest = hmac.new(key, digestmod=hashlib.sha256)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def authentication_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".hmac")


def write_authentication(path: Path, destination: Path | None = None) -> None:
    passphrase = os.environ.get("BACKUP_ENCRYPTION_PASSPHRASE", "")
    if not passphrase:
        raise RuntimeError("define BACKUP_ENCRYPTION_PASSPHRASE")
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, AUTH_ITERATIONS, dklen=32)
    payload = {
        "format_version": 1,
        "algorithm": "hmac-sha256",
        "kdf": "pbkdf2-sha256",
        "iterations": AUTH_ITERATIONS,
        "salt_hex": salt.hex(),
        "hmac_hex": hmac_sha256_file(path, key),
    }
    target = destination or authentication_path(path)
    target.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="ascii")


def validate_authentication(path: Path) -> None:
    auth_path = authentication_path(path)
    if not auth_path.is_file():
        raise RuntimeError("falta autenticación HMAC del backup")
    try:
        payload = json.loads(auth_path.read_text(encoding="ascii"))
        salt = bytes.fromhex(payload["salt_hex"])
        expected = payload["hmac_hex"].lower()
        iterations = int(payload["iterations"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("metadatos HMAC inválidos") from exc
    if (
        payload.get("format_version") != 1
        or payload.get("algorithm") != "hmac-sha256"
        or payload.get("kdf") != "pbkdf2-sha256"
        or iterations != AUTH_ITERATIONS
        or len(salt) != 16
        or not re.fullmatch(r"[0-9a-f]{64}", expected)
    ):
        raise RuntimeError("parámetros HMAC del backup no soportados")
    passphrase = os.environ.get("BACKUP_ENCRYPTION_PASSPHRASE", "")
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations, dklen=32)
    actual = hmac_sha256_file(path, key)
    if not hmac.compare_digest(actual, expected):
        raise RuntimeError("autenticación HMAC del backup no coincide")


class Compose:
    def __init__(self, env_file: Path, project: str, profile: str) -> None:
        self.profile = profile
        self.args = [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-p",
            project,
            "-f",
            "docker-compose.yml",
        ]
        if profile == "production":
            self.args.extend(["-f", "infrastructure/compose/docker-compose.prod.example.yml"])
        self.args.extend(["--profile", profile])

    def call(self, *args: str, capture: bool = True) -> str:
        return run([*self.args, *args], capture=capture)

    def container(self, service: str) -> str:
        container_id = self.call("ps", "-q", service)
        if not container_id:
            raise RuntimeError(f"el servicio {service} no está iniciado")
        return container_id

    def services(self) -> list[str]:
        return [line for line in self.call("config", "--services").splitlines() if line]


def component_specs(profile: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    databases = [("bridge-db", "bridge-db.dump")]
    volumes = [
        ("bridge_uploads", "bridge-uploads.tar"),
        ("bridge_automation_email", "bridge-automation-email.tar"),
    ]
    if profile == "full":
        databases.extend(
            [("chatwoot-db", "chatwoot-db.dump"), ("activepieces-db", "activepieces-db.dump")]
        )
        volumes.extend(
            [
                ("chatwoot_storage_data", "chatwoot-storage.tar"),
                ("activepieces_cache", "activepieces-cache.tar"),
            ]
        )
    return databases, volumes


def release_manifest_path(values: dict[str, str]) -> Path:
    configured = values.get("RELEASE_MANIFEST_FILE", "")
    path = Path(configured)
    path = path if path.is_absolute() else ROOT / path
    path = path.resolve()
    if path.parent != ROOT.resolve() or not re.fullmatch(
        r"\.env\.[a-z0-9][a-z0-9-]{1,48}\.release\.json", path.name
    ):
        raise RuntimeError("RELEASE_MANIFEST_FILE no usa el nombre seguro esperado")
    if not path.is_file():
        raise RuntimeError("no existe RELEASE_MANIFEST_FILE para incluirlo en el backup production")
    return path


def writer_services(profile: str) -> list[str]:
    services = ["bridge-api"]
    if profile == "full":
        services.extend(["chatwoot-web", "chatwoot-worker", "activepieces-app", "activepieces-worker"])
    return services


def stop_writers(compose: Compose, profile: str) -> list[str]:
    if os.getenv("BACKUP_QUIESCE", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        log("WARNING: BACKUP_QUIESCE=false; los archivos se copiarán sin una barrera de escritura")
        return []
    running: list[str] = []
    for service in writer_services(profile):
        try:
            container_id = compose.container(service)
        except RuntimeError:
            continue
        state = run(["docker", "inspect", "-f", "{{.State.Status}}", container_id])
        if state == "running":
            running.append(container_id)
    stopped: list[str] = []
    try:
        if running:
            log(f"Quiesce: deteniendo {len(running)} procesos escritores")
        for container_id in running:
            run(["docker", "stop", "--timeout", "120", container_id], capture=False)
            stopped.append(container_id)
        return stopped
    except Exception:
        start_containers(stopped)
        raise


def start_containers(container_ids: list[str]) -> None:
    if container_ids:
        run(["docker", "start", *container_ids], capture=False)


def wait_healthy(compose: Compose, timeout: int = 600) -> None:
    services = compose.services()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        all_ready = True
        for service in services:
            try:
                container_id = compose.container(service)
            except RuntimeError:
                all_ready = False
                break
            status = run(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                    container_id,
                ]
            )
            if status != "running healthy":
                all_ready = False
                break
        if all_ready:
            return
        time.sleep(5)
    raise RuntimeError(f"el perfil {compose.profile} no recuperó health en {timeout}s")


def dump_database(compose: Compose, service: str, output: Path) -> None:
    container_id = compose.container(service)
    remote = f"/tmp/agent-platform-{uuid.uuid4().hex}.dump"
    try:
        run(
            [
                "docker",
                "exec",
                container_id,
                "sh",
                "-ec",
                f'pg_dump -Fc --no-owner --no-acl -U "$POSTGRES_USER" "$POSTGRES_DB" -f "{remote}"',
            ],
            capture=False,
        )
        run(["docker", "cp", f"{container_id}:{remote}", str(output)], capture=False)
    finally:
        subprocess.run(["docker", "exec", container_id, "rm", "-f", remote], capture_output=True)
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"dump vacío para {service}")


def helper_image(values: dict[str, str]) -> str:
    image = values.get("BACKUP_HELPER_IMAGE") or values.get("NGINX_IMAGE") or HELPER_IMAGE
    if not re.search(r"@sha256:[0-9a-fA-F]{64}$", image):
        raise RuntimeError("BACKUP_HELPER_IMAGE/NGINX_IMAGE debe estar fijada por digest")
    return image


def archive_volume(image: str, volume: str, output: Path) -> None:
    stage = output.parent.resolve()
    run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:mode=1777",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "DAC_READ_SEARCH",
            "--security-opt",
            "no-new-privileges:true",
            "-v",
            f"{volume}:/data:ro",
            "-v",
            f"{stage}:/backup",
            "--entrypoint",
            "sh",
            image,
            "-ec",
            f"tar -C /data -cf /backup/{output.name} .",
        ],
        capture=False,
    )
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"archivo de volumen vacío: {volume}")


def write_checksums(stage: Path, files: list[str]) -> None:
    lines = [f"{sha256_file(stage / name)}  {name}" for name in files]
    (stage / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii")


def create_backup(
    *, client_id: str, env_file: Path, values: dict[str, str], compose: Compose, project: str
) -> Path:
    profile = compose.profile
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = ROOT / "infrastructure" / "backups" / client_id
    base.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{timestamp}.", suffix=".stage", dir=base))
    output = base / f"{client_id}-{timestamp}-{uuid.uuid4().hex[:8]}.tar.gz.enc"
    partial = output.with_suffix(output.suffix + ".partial")
    auth_partial = authentication_path(output).with_suffix(".hmac.partial")
    databases, volumes = component_specs(profile)
    stopped: list[str] = []
    artifact_finalized = False
    try:
        stopped = stop_writers(compose, profile)
        for service, filename in databases:
            log(f"Backup PostgreSQL: {service}")
            dump_database(compose, service, stage / filename)
        image = helper_image(values)
        for volume_suffix, filename in volumes:
            volume = f"{project}_{volume_suffix}"
            run(["docker", "volume", "inspect", volume])
            log(f"Backup volumen: {volume}")
            archive_volume(image, volume, stage / filename)
        shutil.copy2(env_file, stage / "deployment.env")
        files = [filename for _, filename in databases] + [filename for _, filename in volumes] + ["deployment.env"]
        if profile == "production":
            shutil.copy2(release_manifest_path(values), stage / "release-manifest.json")
            files.append("release-manifest.json")
        manifest = {
            "format_version": 4,
            "client_id": client_id,
            "project": project,
            "profile": profile,
            "created_at_utc": timestamp,
            "git_commit": run(["git", "rev-parse", "HEAD"]),
            "encrypted": True,
            "config_sha256": sha256_file(stage / "deployment.env"),
            "files": files,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        files.append("manifest.json")
        write_checksums(stage, files)
        package = stage / "package.tar.gz"
        with tarfile.open(package, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for name in [*files, "SHA256SUMS"]:
                archive.add(stage / name, arcname=name, recursive=False)
        run(
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
                str(partial),
            ],
            capture=False,
        )
        write_authentication(partial, auth_partial)
        partial.replace(output)
        auth_partial.replace(authentication_path(output))
        output.with_suffix(output.suffix + ".sha256").write_text(
            f"{sha256_file(output)}  {output.name}\n", encoding="ascii"
        )
        artifact_finalized = True
        log(f"Conservar juntos: {output.name}, {authentication_path(output).name} y {output.name}.sha256")
        return output
    finally:
        if partial.exists():
            partial.unlink()
        if auth_partial.exists():
            auth_partial.unlink()
        if not artifact_finalized:
            for incomplete in (
                output,
                authentication_path(output),
                output.with_suffix(output.suffix + ".sha256"),
            ):
                incomplete.unlink(missing_ok=True)
        active_exception = sys.exc_info()[0] is not None
        try:
            start_containers(stopped)
            if stopped:
                wait_healthy(compose)
        except Exception as restart_error:
            if active_exception:
                log(f"ERROR adicional al reanudar servicios: {restart_error}")
            else:
                raise
        shutil.rmtree(stage, ignore_errors=True)


def normalized_member(name: str) -> str:
    while name.startswith("./"):
        name = name[2:]
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"ruta insegura en archive: {name}")
    return str(path)


def decrypt_and_extract(archive_path: Path, temp: Path) -> dict[str, object]:
    validate_authentication(archive_path)
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    if checksum_path.is_file():
        expected = checksum_path.read_text(encoding="ascii").split()[0].lower()
        if expected != sha256_file(archive_path):
            raise RuntimeError("checksum externo del backup no coincide")
    else:
        log("WARNING: falta checksum externo .sha256; se validarán los checksums internos")
    package = temp / "package.tar.gz"
    run(
        [
            "openssl",
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-iter",
            "200000",
            "-pass",
            "env:BACKUP_ENCRYPTION_PASSPHRASE",
            "-in",
            str(archive_path),
            "-out",
            str(package),
        ],
        capture=False,
    )
    with tarfile.open(package, "r:gz") as source:
        members = source.getmembers()
        names = {normalized_member(member.name) for member in members}
        if not names.issubset(ALLOWED_PACKAGE_FILES):
            raise RuntimeError(f"archive contiene entradas no permitidas: {sorted(names - ALLOWED_PACKAGE_FILES)}")
        if not {"manifest.json", "deployment.env", "SHA256SUMS"}.issubset(names):
            raise RuntimeError("archive incompleto: faltan manifiesto/config/checksums")
        for member in members:
            name = normalized_member(member.name)
            if not member.isfile():
                raise RuntimeError(f"tipo de entrada no permitido en package: {name}")
            stream = source.extractfile(member)
            if stream is None:
                raise RuntimeError(f"no se pudo leer {name}")
            with (temp / name).open("wb") as destination:
                shutil.copyfileobj(stream, destination)
    allowed_checksum_names: set[str] = set()
    for raw in (temp / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        digest, name = raw.split(None, 1)
        name = normalized_member(name.strip().lstrip("*"))
        if name not in ALLOWED_PACKAGE_FILES or name == "SHA256SUMS":
            raise RuntimeError(f"checksum referencia archivo no permitido: {name}")
        target = temp / name
        if not target.is_file() or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise RuntimeError(f"checksum inválido para {name}")
        if sha256_file(target) != digest.lower():
            raise RuntimeError(f"checksum interno incorrecto: {name}")
        allowed_checksum_names.add(name)
    manifest = json.loads((temp / "manifest.json").read_text(encoding="utf-8"))
    expected = set(manifest.get("files", [])) | {"manifest.json"}
    if expected != allowed_checksum_names:
        raise RuntimeError("manifiesto y SHA256SUMS no describen el mismo contenido")
    return manifest


def validate_volume_tar(path: Path) -> None:
    with tarfile.open(path, "r:") as archive:
        for member in archive.getmembers():
            normalized_member(member.name)
            if not (member.isfile() or member.isdir()):
                raise RuntimeError(f"tipo no permitido en volumen {path.name}: {member.name}")


def copy_dump_to_container(compose: Compose, service: str, dump: Path) -> tuple[str, str]:
    container_id = compose.container(service)
    remote = f"/tmp/agent-platform-{uuid.uuid4().hex}.dump"
    run(["docker", "cp", str(dump), f"{container_id}:{remote}"], capture=False)
    return container_id, remote


def verify_database_dump(compose: Compose, service: str, dump: Path) -> None:
    container_id, remote = copy_dump_to_container(compose, service, dump)
    verify_db = f"restore_verify_{uuid.uuid4().hex[:20]}"
    try:
        run(
            [
                "docker",
                "exec",
                "-e",
                f"VERIFY_DB={verify_db}",
                container_id,
                "sh",
                "-ec",
                f'createdb -U "$POSTGRES_USER" "$VERIFY_DB"; trap \'dropdb -U "$POSTGRES_USER" --if-exists "$VERIFY_DB"; rm -f "{remote}"\' EXIT; pg_restore --no-owner --no-acl --exit-on-error -U "$POSTGRES_USER" -d "$VERIFY_DB" "{remote}"',
            ],
            capture=False,
        )
    finally:
        subprocess.run(["docker", "exec", container_id, "rm", "-f", remote], capture_output=True)


def restore_database(compose: Compose, service: str, dump: Path) -> None:
    container_id, remote = copy_dump_to_container(compose, service, dump)
    try:
        run(
            [
                "docker",
                "exec",
                container_id,
                "sh",
                "-ec",
                f'pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error -U "$POSTGRES_USER" -d "$POSTGRES_DB" "{remote}"',
            ],
            capture=False,
        )
    finally:
        subprocess.run(["docker", "exec", container_id, "rm", "-f", remote], capture_output=True)


def restore_volume(image: str, volume: str, archive: Path) -> None:
    run(["docker", "volume", "inspect", volume])
    stage = archive.parent.resolve()
    run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:mode=1777",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "CHOWN",
            "--cap-add",
            "DAC_OVERRIDE",
            "--cap-add",
            "FOWNER",
            "--security-opt",
            "no-new-privileges:true",
            "-v",
            f"{volume}:/data",
            "-v",
            f"{stage}:/backup:ro",
            "--entrypoint",
            "sh",
            image,
            "-ec",
            f"find /data -mindepth 1 -delete && tar -C /data -xf /backup/{archive.name}",
        ],
        capture=False,
    )


def restore_backup(
    *, client_id: str, archive: Path, env_file: Path, values: dict[str, str], compose: Compose, project: str
) -> Path:
    with tempfile.TemporaryDirectory(prefix="agent-restore-") as temporary:
        temp = Path(temporary)
        manifest = decrypt_and_extract(archive, temp)
        if manifest.get("format_version") != 4:
            raise RuntimeError("formato de backup no soportado; se requiere version 4")
        if manifest.get("client_id") != client_id or manifest.get("project") != project:
            raise RuntimeError("el backup pertenece a otra instalación/proyecto")
        if manifest.get("profile") != compose.profile:
            raise RuntimeError(f"backup profile={manifest.get('profile')} != destino profile={compose.profile}")
        if manifest.get("config_sha256") != sha256_file(temp / "deployment.env"):
            raise RuntimeError("fingerprint de configuración del manifiesto inválido")
        if sha256_file(env_file) != manifest.get("config_sha256"):
            raise RuntimeError(
                "el .env actual no coincide con el backup; restaura primero deployment.env de forma controlada"
            )
        databases, volumes = component_specs(compose.profile)
        expected_files = {name for _, name in databases} | {name for _, name in volumes} | {"deployment.env"}
        if compose.profile == "production":
            expected_files.add("release-manifest.json")
            if sha256_file(release_manifest_path(values)) != sha256_file(temp / "release-manifest.json"):
                raise RuntimeError("el release manifest actual no coincide con el backup")
        if set(manifest.get("files", [])) != expected_files:
            raise RuntimeError("los componentes del manifiesto no corresponden al perfil de destino")
        for _, filename in volumes:
            validate_volume_tar(temp / filename)
        for service, filename in databases:
            log(f"Verificación de restore aislado: {service}")
            verify_database_dump(compose, service, temp / filename)

        safety = create_backup(
            client_id=client_id, env_file=env_file, values=values, compose=compose, project=project
        )
        log(f"Backup de seguridad previo al restore: {safety}")
        stopped: list[str] = []
        try:
            stopped = stop_writers(compose, compose.profile)
            for service, filename in databases:
                log(f"Restore PostgreSQL: {service}")
                restore_database(compose, service, temp / filename)
            image = helper_image(values)
            for suffix, filename in volumes:
                log(f"Restore volumen: {project}_{suffix}")
                restore_volume(image, f"{project}_{suffix}", temp / filename)
        finally:
            start_containers(stopped)
        compose.call(
            "up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "600", capture=False
        )
        wait_healthy(compose)
        return safety


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("client_id")
    parser.add_argument("archive", nargs="?")
    parser.add_argument("--profile", choices=("core", "full", "production"))
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,48}", args.client_id):
        parser.error("client_id inválido")
    if not os.getenv("BACKUP_ENCRYPTION_PASSPHRASE"):
        raise RuntimeError("define BACKUP_ENCRYPTION_PASSPHRASE")
    for command in ("docker", "openssl", "git"):
        executable = find_executable(command)
        if executable is None:
            raise RuntimeError(f"{command} no está instalado")
        if command == "openssl" and shutil.which("openssl") is None:
            os.environ["PATH"] = str(Path(executable).parent) + os.pathsep + os.environ.get("PATH", "")
    env_file = ROOT / f".env.{args.client_id}"
    if not env_file.is_file():
        raise RuntimeError(f"no existe {env_file.name}")
    values = read_env(env_file)
    profile = args.profile or os.getenv("DEPLOY_PROFILE") or values.get("DEPLOY_PROFILE") or "production"
    if profile not in {"core", "full", "production"}:
        raise RuntimeError(f"perfil no soportado: {profile}")
    project = values.get("COMPOSE_PROJECT_NAME") or f"agent-{args.client_id}"
    if project != f"agent-{args.client_id}":
        raise RuntimeError(f"COMPOSE_PROJECT_NAME debe ser agent-{args.client_id}")
    compose = Compose(env_file, project, profile)
    compose.call("config", "--quiet")
    if args.action == "backup":
        output = create_backup(
            client_id=args.client_id, env_file=env_file, values=values, compose=compose, project=project
        )
        print(output.relative_to(ROOT).as_posix())
        return 0
    if not args.archive:
        parser.error("restore exige la ruta del backup")
    archive = Path(args.archive).resolve()
    if not archive.is_file():
        raise RuntimeError(f"backup no válido: {archive}")
    safety = restore_backup(
        client_id=args.client_id,
        archive=archive,
        env_file=env_file,
        values=values,
        compose=compose,
        project=project,
    )
    print(f"restore=PASS safety_backup={safety.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError, tarfile.TarError, ValueError, KeyError) as exc:
        print(f"backup_restore=FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
