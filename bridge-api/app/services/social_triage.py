"""Triaje determinista de mensajes sociales (Fase 1, propuesta T-056).

Convierte un mensaje entrante normalizado (``SocialEnvelope``) en un veredicto
explicable SIN red ni LLM: la misma entrada produce siempre el mismo resultado
y cada componente se expone para que el comercial entienda el porqué.

Componentes del veredicto:

- ``intent``: lead | queja | consulta | spam | otra. Se puntúa cada intención
  con listas léxicas y se elige la de mayor peso (empates resueltos por
  prioridad de negocio: spam > queja > lead > consulta > otra).
- ``language``: es | en | otro (comparación de frecuencias de stopwords).
- ``register``: formal | tuteo | neutral (marcadores léxicos).
- ``sentiment``: -1.0..1.0 léxico (positivas - negativas normalizadas).
- ``urgency``: 0-100 (marcadores de urgencia + base por intención).
- ``entities``: email, teléfono, SKU y precio extraídos por regex.
- ``score_social``: 0-100 que se FUSIONA en el scoring del lead (``_lead_score``
  añade una señal ``social``); nunca reemplaza el score total.
- ``summary``: resumen determinista (el LLM opcional solo puede enriquecerlo
  con ``decided_by=llm``; jamás decide la mutación).

Hermeticidad D-032: funciones puras sin estado global; los tests la ejercitan
sin red y con corpus multilingüe.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.social_adapters import SocialEnvelope

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,17}\d)")
_SKU_RE = re.compile(r"\b[A-Z]{2,6}[-]?\d{2,6}\b")
_PRICE_RE = re.compile(
    r"\b\d{1,3}(?:[.,]\d{2,3})?\s*(?:€|eur|usd|\$)\b", re.IGNORECASE
)

_INTENT_LEXICON: dict[str, list[str]] = {
    "spam": [
        "sorteo",
        "premio",
        "gana",
        "ganaste",
        "gratis",
        "descargate",
        "descárgate",
        "pincha",
        "pulsa",
        "toca aqui",
        "toca aquí",
        "click aqui",
        "haz click",
        "invierte",
        "cripto",
        "crypto",
        "oportunidad única",
        "hermano",
        "envíanos tu",
        "colaboración comercial",
        "negocio millonario",
    ],
    "queja": [
        "queja",
        "problema",
        "roto",
        "defectuoso",
        "defecto",
        "no funciona",
        "no me funciona",
        "reclamación",
        "devolución",
        "reembolso",
        "reembols",
        "error",
        "tarde",
        "retraso",
        "pésimo",
        "enfadad",
        "cabread",
        "indignad",
        "estafa",
        "no llega",
        "sin respuesta",
    ],
    "lead": [
        "comprar",
        "compra",
        "pedido",
        "quiero comprar",
        "quiero encargar",
        "necesito comprar",
        "interesad",
        "presupuesto",
        "cotización",
        "factura",
        "me interesa",
        "estoy interesado",
        "adquirir",
        "solicitar",
        "licitación",
    ],
    "consulta": [
        "precio",
        "cuánto",
        "cuanto",
        "cuánto cuesta",
        "cuanto cuesta",
        "disponibilidad",
        "stock",
        "envío",
        "plazo de entrega",
        "información",
        "info",
        "duda",
        "consulta",
        "me gustaría saber",
        "quisiera saber",
        "catálogo",
        "especificaciones",
        "ficha técnica",
        "garantía",
    ],
}

_ES_STOPWORDS = {
    "hola",
    "buenos",
    "buenas",
    "dias",
    "días",
    "tardes",
    "gracias",
    "por",
    "favor",
    "quiero",
    "necesito",
    "precio",
    "envío",
    "envio",
    "saludos",
    "para",
    "con",
    "usted",
    "el",
    "la",
    "los",
    "las",
    "me",
    "te",
    "un",
    "una",
    "presupuesto",
}
_EN_STOPWORDS = {
    "hello",
    "hi",
    "good",
    "morning",
    "afternoon",
    "thanks",
    "thank",
    "please",
    "want",
    "need",
    "price",
    "shipping",
    "quote",
    "how",
    "much",
    "what",
    "the",
    "of",
    "and",
    "for",
    "with",
    "a",
    "i",
    "you",
}

_FORMAL_MARKERS = re.compile(
    r"\b(usted|ustedes|le|le agradezco|agradezco|podría|podrían|podria|podrian|"
    r"quisiera|me gustaría|me gustaria|atentamente|cordialmente)\b",
    re.IGNORECASE,
)
_TUTEO_MARKERS = re.compile(
    r"\b(tú|tu|te|ti|tus|quieres|puedes|házme|hazme|mándame|mandame|dime)\b",
    re.IGNORECASE,
)
_URGENT_MARKERS = re.compile(
    r"\b(urgente|ya|hoy|inmediato|inmediatamente|lo antes posible|cuanto antes|"
    r"para ayer|bloquead|se me cae|no puedo)\b",
    re.IGNORECASE,
)
_POSITIVE_MARKERS = re.compile(
    r"\b(gracias|genial|perfecto|me encanta|excelente|buen|buena|bien|estupendo|"
    r"great|thanks|perfect|love|excellent)\b",
    re.IGNORECASE,
)
_NEGATIVE_MARKERS = re.compile(
    r"\b(problema|mal|mala|roto|defectuoso|error|pésimo|enfadado|tarde|retraso|"
    r"estafa|never|bad|broken|error|late|wrong)\b",
    re.IGNORECASE,
)

_INTENT_PRIORITY = ["spam", "queja", "lead", "consulta", "otra"]
_INTENT_BASE_URGENCY = {
    "spam": 0,
    "queja": 40,
    "lead": 25,
    "consulta": 15,
    "otra": 5,
}
_INTENT_BASE_SCORE = {
    "spam": 0,
    "queja": 30,
    "lead": 40,
    "consulta": 25,
    "otra": 10,
}
_INTENT_LABELS = {
    "spam": "Spam",
    "queja": "Queja",
    "lead": "Lead con intención de compra",
    "consulta": "Consulta",
    "otra": "Otro",
}


def _detect_intent(body_lower: str) -> str:
    weights: dict[str, int] = {}
    for intent, keywords in _INTENT_LEXICON.items():
        weights[intent] = sum(
            1 for keyword in keywords if keyword in body_lower
        )
    best = "otra"
    best_weight = 0
    for intent in _INTENT_PRIORITY:
        weight = weights.get(intent, 0)
        if weight > best_weight:
            best_weight = weight
            best = intent
    return best


def _detect_language(body_lower: str) -> str:
    tokens = set(re.findall(r"[a-záéíóúñü]+", body_lower))
    es_hits = len(tokens & _ES_STOPWORDS)
    en_hits = len(tokens & _EN_STOPWORDS)
    if es_hits == en_hits:
        return "otro"
    return "es" if es_hits > en_hits else "en"


def _detect_register(body: str) -> str:
    if _TUTEO_MARKERS.search(body):
        return "tuteo"
    if _FORMAL_MARKERS.search(body):
        return "formal"
    return "neutral"


def _sentiment(body: str) -> float:
    positives = len(_POSITIVE_MARKERS.findall(body))
    negatives = len(_NEGATIVE_MARKERS.findall(body))
    total = positives + negatives
    if total == 0:
        return 0.0
    return round((positives - negatives) / total, 3)


def _detect_urgency(intent: str, body: str) -> int:
    urgency = _INTENT_BASE_URGENCY[intent]
    urgency += 12 * len(_URGENT_MARKERS.findall(body))
    return min(100, urgency)


def _extract_entities(body: str) -> dict[str, Any]:
    email_match = _EMAIL_RE.search(body)
    phone_match = _PHONE_RE.search(body)
    return {
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(1).strip() if phone_match else None,
        "skus": list(dict.fromkeys(_SKU_RE.findall(body))),
        "prices": list(dict.fromkeys(_PRICE_RE.findall(body))),
    }


def _score_social(
    *,
    intent: str,
    sentiment: float,
    entities: dict[str, Any],
    urgency: int,
) -> int:
    score = _INTENT_BASE_SCORE[intent]
    if sentiment > 0.2:
        score += 10
    elif sentiment < -0.2:
        score += 5  # una queja es engagement: requiere respuesta rápida
    if entities.get("email"):
        score += 15
    if entities.get("phone"):
        score += 15
    if urgency >= 50:
        score += 10
    return min(100, score)


def triage_social_message(
    envelope: SocialEnvelope,
    *,
    channel: str = "generic",
) -> dict[str, Any]:
    """Veredicto determinista y explicable de un mensaje social."""

    body = (envelope.body or "").strip()
    body_lower = body.lower()
    intent = _detect_intent(body_lower)
    language = _detect_language(body_lower)
    register = _detect_register(body)
    sentiment = _sentiment(body)
    urgency = _detect_urgency(intent, body)
    entities = _extract_entities(body)

    # Las entidades explícitas del canal (perfil del remitente) complementan
    # las extraídas del texto, sin pisarlas.
    if not entities.get("email") and envelope.email:
        entities["email"] = envelope.email
    if not entities.get("phone") and envelope.phone:
        entities["phone"] = envelope.phone

    score = _score_social(
        intent=intent,
        sentiment=sentiment,
        entities=entities,
        urgency=urgency,
    )

    sender = (
        envelope.sender_name
        or envelope.sender_handle
        or envelope.email
        or envelope.phone
        or "remitente desconocido"
    )
    summary = (
        f"{_INTENT_LABELS[intent]} de {sender}: {body[:120]}"
    )

    return {
        "intent": intent,
        "language": language,
        "register": register,
        "sentiment": sentiment,
        "urgency": urgency,
        "entities": entities,
        "score_social": score,
        "summary": summary,
        "decided_by": "deterministic",
        "channel": channel,
    }
