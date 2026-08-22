"""Router del sistema: liveness, health, readiness y métricas (B-01).

Extraído de ``main.py`` tal cual; los handlers conservan rutas, tags y
comportamiento exactos.
"""

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.models import ApprovalRequest, AuditLog
from app.security import (
    ADMIN_ROLES,
    Principal,
    bearer_scheme,
    get_current_principal,
    require_roles,
)
from app.services.outbox import OutboxService
from app.services.resilience import all_breaker_states

router = APIRouter(tags=["Sistema"])


@router.get("/live")
def get_live():
    return {
        "status": "alive",
        "service": "bridge-api",
        "release_version": settings.APP_VERSION,
    }


@router.get("/health")
def get_health(request: Request, db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as exc:  # noqa: BLE001 - el estado se expone en /health
        logging.getLogger("bridge.api").warning("Health check de BD falló: %s", exc)
        db_status = "unhealthy"
    outbox_worker = getattr(request.app.state, "outbox_worker", None)
    scheduler_worker = getattr(request.app.state, "scheduled_task_worker", None)
    alert_worker = getattr(request.app.state, "alert_delivery_worker", None)
    outbox_ok = not settings.OUTBOX_WORKER_ENABLED or bool(
        outbox_worker is not None and outbox_worker.running
    )
    scheduler_ok = not settings.SCHEDULED_TASK_WORKER_ENABLED or bool(
        scheduler_worker is not None and scheduler_worker.status["running"]
    )
    alerts_ok = not settings.ALERT_DELIVERY_WORKER_ENABLED or bool(
        alert_worker is not None and alert_worker.status["running"]
    )
    healthy = db_status == "healthy" and outbox_ok and scheduler_ok and alerts_ok
    return {
        "status": "ok" if healthy else "degraded",
        "service": "bridge-api",
        "components": {
            "database": db_status == "healthy",
            "outbox_worker": outbox_ok,
            "scheduled_task_worker": scheduler_ok,
            "alert_delivery_worker": alerts_ok,
        },
    }


@router.get("/health/details")
def get_health_details(
    request: Request,
    _: Principal = Depends(require_roles(*ADMIN_ROLES)),
):
    outbox_worker = getattr(request.app.state, "outbox_worker", None)
    scheduler_worker = getattr(request.app.state, "scheduled_task_worker", None)
    alert_worker = getattr(request.app.state, "alert_delivery_worker", None)
    return {
        "installation_id": settings.INSTALLATION_ID,
        "environment": settings.ENVIRONMENT,
        "pilot_mode": settings.PILOT_MODE,
        "outbox_worker": {
            "enabled": settings.OUTBOX_WORKER_ENABLED,
            "running": bool(outbox_worker is not None and outbox_worker.running),
            "last_summary": outbox_worker.last_summary if outbox_worker is not None else {},
        },
        "scheduled_task_worker": (
            scheduler_worker.status
            if scheduler_worker is not None
            else {"enabled": settings.SCHEDULED_TASK_WORKER_ENABLED, "running": False}
        ),
        "alert_delivery_worker": (
            alert_worker.status
            if alert_worker is not None
            else {"enabled": settings.ALERT_DELIVERY_WORKER_ENABLED, "running": False}
        ),
    }


@router.get("/ready")
async def get_ready(request: Request, db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Base de datos no disponible") from exc
    outbox_worker = getattr(request.app.state, "outbox_worker", None)
    if settings.OUTBOX_WORKER_ENABLED and (
        outbox_worker is None or not outbox_worker.running
    ):
        raise HTTPException(status_code=503, detail="Worker de outbox no disponible")
    scheduler_worker = getattr(request.app.state, "scheduled_task_worker", None)
    if settings.SCHEDULED_TASK_WORKER_ENABLED and (
        scheduler_worker is None or not scheduler_worker.status["running"]
    ):
        raise HTTPException(status_code=503, detail="Worker de tareas programadas no disponible")
    alert_worker = getattr(request.app.state, "alert_delivery_worker", None)
    if settings.ALERT_DELIVERY_WORKER_ENABLED and (
        alert_worker is None or not alert_worker.status["running"]
    ):
        raise HTTPException(status_code=503, detail="Worker de entrega de alertas no disponible")
    if settings.REDIS_ENABLED:
        from app.services.redis_backend import RedisBackend

        if not await RedisBackend().check():
            raise HTTPException(status_code=503, detail="Backend Redis no disponible")
    return {"status": "ready"}


@router.get("/metrics")
def get_metrics(_: Principal = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    """Métricas operativas: contadores, estado de outbox y circuit breakers.

    Las alertas D-028 se evalúan en cada llamada para garantizar que
    cualquier operador que monitorice el endpoint vea el estado
    inmediato de los proveedores y de la cola durable.
    """

    from app.services.observability import (
        evaluate_breaker_rule,
        evaluate_outbox_rule,
        get_alert_sink,
    )

    outbox_counts = OutboxService(db).counts()
    breakers = all_breaker_states()
    breaker_alerts = evaluate_breaker_rule(breakers)
    outbox_alerts = evaluate_outbox_rule(outbox_counts)
    return {
        "audit_logs_count": db.query(AuditLog).count(),
        "total_approvals": db.query(ApprovalRequest).count(),
        "pending_approvals": db.query(ApprovalRequest).filter(ApprovalRequest.status == "pending").count(),
        "outbox": outbox_counts,
        "circuit_breakers": breakers,
        "alerts": {
            "recent": [
                {
                    "rule_id": event.rule_id,
                    "summary": event.summary,
                    "severity": event.severity,
                    "details": event.details,
                }
                for event in get_alert_sink().events[-20:]
            ],
            "open_count": len([event for event in get_alert_sink().events if event.severity == "critical"]),
            "evaluated": {
                "circuit_breaker_open": [event.summary for event in breaker_alerts],
                "outbox_dead_letter_growth": [event.summary for event in outbox_alerts],
            },
        },
    }


def _prometheus_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    x_prometheus_token: str | None = Header(default=None, alias="X-Prometheus-Token"),
) -> Principal:
    """Auth de scraping: token dedicado si existe, si no sesión admin.

    Con ``PROMETHEUS_METRICS_TOKEN`` el collector hace scrape sin JWT
    (patrón estándar de Prometheus); sin token configurado, el acceso
    exige exactamente lo mismo que ``/metrics``.
    """

    expected_token = settings.PROMETHEUS_METRICS_TOKEN.strip()
    if expected_token:
        if hmac.compare_digest(expected_token, x_prometheus_token or ""):
            return Principal(
                user_id="prometheus-scraper",
                username="prometheus-scraper",
                role="admin",
                installation_id=settings.INSTALLATION_ID,
                token_version=0,
                jti="prometheus-scraper",
            )
        raise HTTPException(status_code=401, detail="Token de scraping inválido")
    return get_current_principal(request=request, credentials=credentials, db=db)


@router.get("/metrics/prometheus", tags=["Telemetría"])
def get_metrics_prometheus(
    _: Principal = Depends(_prometheus_principal),
):
    """Exposición en formato texto Prometheus para scraping externo.

    SS-07: las métricas in-proceso son inútiles si nadie las recoge. Un
    collector (Prometheus/vmagent) puede hacer scrape sin sesión
    interactiva usando el token dedicado.
    """

    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        payload = generate_latest()
        media_type = CONTENT_TYPE_LATEST
    except ImportError:  # pragma: no cover - entorno sin prometheus-client
        payload = b"# metrics unavailable\n"
        media_type = "text/plain; version=0.0.4"
    return Response(content=payload, media_type=media_type)
