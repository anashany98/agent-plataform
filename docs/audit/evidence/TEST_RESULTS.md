> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# Evidencia de tests

Fecha: 2026-08-02.

Comando equivalente ejecutado en contenedor aislado, con código/tests montados read-only:

```text
PYTHONPATH=/work/bridge python -m pytest -q \
  --cov=/work/bridge/app --cov-report=term-missing /work/tests
```

Resultado:

```text
31 passed, 2 warnings in 4.96s
Python 3.12.13, Linux
```

Warnings relevantes:

- Starlette depreca el uso actual de `httpx` con `TestClient` y recomienda `httpx2`.
- Pytest no pudo crear `.pytest_cache` porque los tests estaban protegidos read-only; no afecta al resultado.

Límite: SQLite, demo, mocks/stubs, TF-IDF local y rate limit deshabilitado. No es E2E externo.
