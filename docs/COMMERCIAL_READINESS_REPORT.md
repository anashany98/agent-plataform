> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Informe histórico de la remediación previa (31/07/2026). Sus afirmaciones de estado, pruebas y cobertura quedaron invalidadas por la reproducción de Fase 1 (defectos P0 rojos) y por la remediación posterior en la rama `production-remediation`. El único estado autoritativo es `docs/PRODUCTION_READINESS.md`.

# Preparación comercial

## Estado

**No preparado todavía para entrega directa a cliente.**  
**Preparado para staging controlado.**

## Razón

El código propio ha sido remediado y probado, pero las capacidades que dependen de infraestructuras externas no pueden declararse verificadas sin ejecutar:

- Docker completo.
- Chatwoot real.
- PrestaShop real.
- GHL real.
- Activepieces real.
- Proveedor de IA real.
- Backup/restore real.
- Pruebas visuales y de carga.

## Criterio de avance

Solo se autoriza un piloto de Ofideep al completar y firmar `LIVE_VALIDATION_CHECKLIST.md`.
