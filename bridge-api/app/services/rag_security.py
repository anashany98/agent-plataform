"""Clasificación, DLP y defensa contra prompt injection para RAG (D-020).

Reglas:

- Clasificación de documentos: ``public`` (visible incluso para el rol
  sintético ``public`` del canal de chat), ``internal`` (cualquier rol
  autenticado del portal; es el nivel por defecto), ``confidential``
  (solo roles presentes en la ACL ``allowed_roles``; la ACL vacía o
  ausente niega el acceso) y ``restricted`` (fuera de toda búsqueda).
- DLP: patrones deterministas de secretos (claves API, AWS, claves
  privadas, tarjetas con Luhn, IBAN y DNI/NIE). En ingesta elevan la
  clasificación como mínimo a ``confidential`` y se registran los tipos
  detectados (nunca los valores). En la respuesta, los secretos se
  redactan en respuesta y citas aunque el lector esté autorizado: el
  resultado de búsqueda alimenta canales de chat/IA y no debe propagar
  secretos en crudo.
- El contenido de los documentos es DATO, nunca instrucciones: ningún
  resultado RAG ejecuta efectos y el material recuperado se marca como
  no confiable para el consumidor.
"""

from __future__ import annotations

import re

# Nivel sintético del canal de chat externo; no es un rol de portal.
PUBLIC_CONTEXT_ROLE = "public"

CLASSIFICATION_LEVELS = ("public", "internal", "confidential", "restricted")

_PORTAL_ROLES = frozenset(
    {"provider_admin", "client_admin", "supervisor", "commercial", "support", "operator", "viewer"}
)

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_DNI_PATTERN = re.compile(r"\b\d{8}[A-Za-z]\b")
_NIE_PATTERN = re.compile(r"\b[XYZxyz]\d{7}[A-Za-z]\b")
_IBAN_PATTERN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){10,30}\b")
_LUHN_PATTERN = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_API_KEY_PATTERN = re.compile(r"\bapi[_-]?key\b.{0,80}?\b[a-z0-9_-]{20,}\b", re.IGNORECASE)
_VENDOR_KEY_PATTERN = re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[a-z0-9]{10,}\b", re.IGNORECASE)
_JWT_PATTERN = re.compile(r"\beyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\b", re.IGNORECASE)
_BEARER_PATTERN = re.compile(r"\bbearer\s+[a-z0-9._\-]{20,}\b", re.IGNORECASE)
_PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_AWS_ACCESS_KEY_PATTERN = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_GENERIC_SECRET_ASSIGNMENT = re.compile(
    r"\b(?:secret|token|password|passwd|pwd)(?:[_-]?key|[_-]?value)?\b\s*[:=]\s*['\"]?[a-z0-9_\-]{20,}",
    re.IGNORECASE,
)

_DLP_DETECTORS: tuple[tuple[str, re.Pattern], ...] = (
    ("private_key", _PRIVATE_KEY_PATTERN),
    ("aws_access_key", _AWS_ACCESS_KEY_PATTERN),
    ("api_key", _API_KEY_PATTERN),
    ("api_key", _VENDOR_KEY_PATTERN),
    ("jwt", _JWT_PATTERN),
    ("bearer_token", _BEARER_PATTERN),
    ("generic_secret", _GENERIC_SECRET_ASSIGNMENT),
)

# Secuencias de inyección de prompt conocidas. No es una defensa completa
# (la ACL es la barrera real), pero permite auditar y bloquear consultas
# que intentan saltarse las instrucciones del sistema.
_INJECTION_PATTERN = re.compile(
    r"(?:ignore|ignora|olvida|desatiende|disregard)\b.{0,80}?\b(?:instrucci[oó]n|instruction|prompt)"
    r"|revela\b.{0,60}?\b(?:system|sistema)\s*prompt"
    r"|\b(?:system|sistema)\s*prompt\b.{0,60}?\b(?:revela|muestra|ense[añ]a|reveal|show)"
    r"|hazte pasar por"
    r"|nuevo role?play"
    r"|developer mode"
    r"|jailbreak"
    r"|DAN mode",
    re.IGNORECASE,
)


def normalize_classification(value: object) -> str:
    """Valida la clasificación pedida; rechaza valores desconocidos."""

    if value is None:
        return "internal"
    if not isinstance(value, str) or value.strip().lower() not in CLASSIFICATION_LEVELS:
        raise ValueError(f"Clasificación desconocida: {value!r}")
    return value.strip().lower()


def effective_classification(requested: str | None, dlp_findings: set[str]) -> str:
    """La clasificación efectiva nunca baja de confidential si hay secretos."""

    level = normalize_classification(requested)
    if dlp_findings and level in ("public", "internal"):
        return "confidential"
    return level


def detect_dlp(text: str) -> set[str]:
    """Devuelve los TIPOS de secreto presentes en el texto (nunca valores)."""

    found: set[str] = set()
    for name, pattern in _DLP_DETECTORS:
        if pattern.search(text):
            found.add(name)
    for match in _IBAN_PATTERN.finditer(text):
        if _iban_valid(match.group(0)):
            found.add("iban")
            break
    for match in _DNI_PATTERN.finditer(text):
        candidate = match.group(0)
        if candidate[:-1] and candidate[-1].upper() == _DNI_LETTERS[int(candidate[:8]) % 23]:
            found.add("dni")
            break
    if "dni" not in found:
        for match in _NIE_PATTERN.finditer(text):
            candidate = match.group(0).upper()
            prefix_value = {"X": "0", "Y": "1", "Z": "2"}[candidate[0]]
            if candidate[-1] == _DNI_LETTERS[int(prefix_value + candidate[1:8]) % 23]:
                found.add("dni")
                break
    for match in _LUHN_PATTERN.finditer(text):
        digits = [int(ch) for ch in match.group(0) if ch.isdigit()]
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            found.add("card_number")
            break
    return found


def _iban_valid(candidate: str) -> bool:
    compact = candidate.replace(" ", "").upper()
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)
    return digits.isdigit() and int(digits) % 97 == 1


def _luhn_valid(digits: list[int]) -> bool:
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def redact_text(text: str) -> tuple[str, set[str]]:
    """Redacta secretos del texto; devuelve el texto limpio y los tipos."""

    found = detect_dlp(text)
    if not found:
        return text, set()
    redacted = text
    for name, pattern in _DLP_DETECTORS:
        if name in found:
            redacted = pattern.sub(f"[REDACTED:{name}]", redacted)
    if "iban" in found:
        redacted = _IBAN_PATTERN.sub("[REDACTED:iban]", redacted)
    if "dni" in found:
        redacted = _DNI_PATTERN.sub("[REDACTED:dni]", redacted)
        redacted = _NIE_PATTERN.sub("[REDACTED:dni]", redacted)
    if "card_number" in found:
        def _card_repl(match: re.Match) -> str:
            digits = [ch for ch in match.group(0) if ch.isdigit()]
            return f"[REDACTED:card_number:{len(digits)}]"

        redacted = _LUHN_PATTERN.sub(_card_repl, redacted)
    return redacted, found


def looks_like_injection(query: str) -> bool:
    return bool(_INJECTION_PATTERN.search(query))


def can_read(
    *,
    classification: str | None,
    allowed_roles: object,
    role: str | None,
) -> bool:
    """ACL deny-by-default combinada con clasificación.

    ``restricted`` queda fuera de toda búsqueda; ``confidential`` exige
    pertenecer a la ACL explícita; ``internal`` exige un rol de portal;
    ``public`` permite también el contexto sintético ``public`` del chat.
    """

    level = (classification or "").strip().lower()
    if level not in CLASSIFICATION_LEVELS:
        # Documento legado sin clasificación reconocible: se aplica la
        # semántica estricta previa (solo ACL explícita y no vacía).
        return (
            role is not None
            and isinstance(allowed_roles, list)
            and bool(allowed_roles)
            and all(isinstance(item, str) for item in allowed_roles)
            and role in allowed_roles
        )
    if level == "restricted":
        return False
    if role is None:
        return False
    if level == "public":
        return True
    if role == PUBLIC_CONTEXT_ROLE:
        return False
    if role not in _PORTAL_ROLES:
        return False
    if level == "internal":
        return True
    # confidential: solo ACL explícita y no vacía
    return (
        isinstance(allowed_roles, list)
        and bool(allowed_roles)
        and all(isinstance(item, str) for item in allowed_roles)
        and role in allowed_roles
    )
