import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.models import User


PBKDF2_ITERATIONS = 310_000
PASSWORD_MIN_LENGTH = 12


def validate_password_policy(password: str) -> None:
    checks = (
        len(password) >= PASSWORD_MIN_LENGTH,
        bool(re.search(r"[A-ZÁÉÍÓÚÜÑ]", password)),
        bool(re.search(r"[a-záéíóúüñ]", password)),
        bool(re.search(r"\d", password)),
        bool(re.search(r"[^\w\s]", password)),
    )
    if not all(checks):
        raise ValueError("La contraseña debe tener al menos 12 caracteres, mayúscula, minúscula, número y símbolo")


def hash_password(password: str, salt: bytes | None = None) -> str:
    validate_password_policy(password)
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user: User) -> str:
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "installation_id": user.installation_id,
        "token_version": int(user.token_version or 0),
        "jti": _b64(os.urandom(18)),
        "iat": now,
        "exp": now + settings.AUTH_TOKEN_TTL_SEC,
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(settings.AUTH_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    role: str
    installation_id: str
    token_version: int
    jti: str


def decode_access_token(token: str) -> Principal:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}"
        expected = hmac.new(settings.AUTH_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(signature_b64)):
            raise ValueError("invalid signature")
        header = json.loads(_unb64(header_b64))
        if header.get("alg") != "HS256" or header.get("typ") != "JWT":
            raise ValueError("invalid header")
        payload = json.loads(_unb64(payload_b64))
        now = int(dt.datetime.now(dt.timezone.utc).timestamp())
        if int(payload["exp"]) <= now or int(payload.get("iat", 0)) > now + 60:
            raise ValueError("expired or invalid time")
        if payload.get("installation_id") != settings.INSTALLATION_ID:
            raise ValueError("wrong installation")
        return Principal(
            user_id=str(payload["sub"]),
            username=str(payload["username"]),
            role=str(payload["role"]),
            installation_id=str(payload["installation_id"]),
            token_version=int(payload.get("token_version", -1)),
            jti=str(payload.get("jti", "")),
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token no válido o caducado") from exc


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticación requerida")
    principal = decode_access_token(credentials.credentials)
    user = db.query(User).filter(User.id == principal.user_id, User.is_active.is_(True)).first()
    if not user or user.installation_id != settings.INSTALLATION_ID:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario desactivado o inexistente")
    if int(user.token_version or 0) != principal.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesión ha sido revocada")
    if user.role != principal.role or user.username != principal.username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesión ya no coincide con el usuario")
    allowed_during_password_change = {"/auth/change-password", "/auth/logout"}
    if user.must_change_password and request.url.path not in allowed_during_password_change:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Debes cambiar la contraseña temporal antes de continuar",
        )
    return principal


def require_roles(*roles: str) -> Callable[[Principal], Principal]:
    allowed = set(roles)

    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permisos insuficientes")
        return principal

    return dependency


ALL_ROLES = ("provider_admin", "client_admin", "supervisor", "commercial", "support", "operator", "viewer")
ADMIN_ROLES = ("provider_admin", "client_admin")
OPERATOR_ROLES = (*ADMIN_ROLES, "supervisor", "commercial", "support", "operator")
READ_ROLES = (*OPERATOR_ROLES, "viewer")
