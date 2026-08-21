> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# Extractos de runtime relevantes

Solo errores/warnings vinculados a la auditoría; sin secretos ni logs completos.

## Chatwoot

```text
A server is already running (pid: 1, file: /app/tmp/pids/server.pid).
```

Efecto: restart loop; 43 reinicios en la última captura antes del cierre.

## Reverse proxy

```text
setuid(101) failed (1: Operation not permitted)
signal 17 (SIGCHLD) received
unknown process ... exited with code 1
```

Efecto: master sin workers; health `wget` acumulados.

## Activepieces

```text
Socket.IO connection errors
RPC [poll] failed (timeout: 60000ms)
```

Efecto observado: CPU/tráfico elevado entre app y Redis. Causalidad funcional adicional no demostrada.

## Bridge hacia Ollama

```text
httpx.ConnectError: [Errno 101] Network is unreachable
```

Efecto: ausencia de default route en redes internas.
