# Resolución de problemas

## Captura segura inicial

Trabaje desde el checkout dedicado y use siempre el mismo `--env-file`, `-p` y perfil del cliente. Antes de cambiar nada, capture:

```powershell
docker compose --env-file .env.<client> -p agent-<client> `
  -f docker-compose.yml `
  -f infrastructure/compose/docker-compose.prod.example.yml `
  --profile production ps

docker compose --env-file .env.<client> -p agent-<client> `
  -f docker-compose.yml `
  -f infrastructure/compose/docker-compose.prod.example.yml `
  --profile production logs --since 15m --no-color
```

Redacte bearer, cookies, passwords, DSN, claves, cuerpos sensibles y paths de secretos antes de compartir. Anote UTC, instalación, release/commit, request ID y cambios recientes.

## Preflight falla

### Versión o manifest

Síntomas: `dev`, tag mutable, `SOURCE_COMMIT` desconocido o manifest incoherente.

- Use el archivo generado por provisionado; debe llevar `0.9.1-<sha12>`.
- Confirme que `APP_VERSION`, `RELEASE_VERSION`, labels, manifest y commit coinciden.
- No edite valores para hacer pasar el gate ni use `latest`.

### Disco insuficiente

El preflight bloquea por debajo de 15 GiB y se recomiendan 30 GiB libres. El host auditado estaba cerca del mínimo. Retire de forma controlada artefactos ajenos/antiguos según política o mueva Docker/backups a un volumen dedicado; no ejecute un prune global sin inventario y aprobación.

### TLS/DNS

- Verifique que el certificado leaf cubre `PORTAL_HOST` y `API_HOST` en SAN.
- Confirme cadena completa, clave correspondiente, permisos y fecha.
- Resuelva DNS desde fuera de la red y pruebe SNI.
- Autofirmado solo es admisible en bootstrap aislado si se autorizó; nunca en release.

### Configuración insegura

El modo release rechaza debug, demo, mocks, stubs, SQLite, CORS/hosts abiertos, secretos débiles, imágenes mutables, rate limit fail-open o outbox desactivado. Corrija la fuente de configuración; no rebaje el preflight.

## Servicio unhealthy o reiniciando

1. Identifique el primer servicio que falló, no solo el dependiente.
2. Revise los últimos logs y `docker inspect` sin imprimir variables secretas.
3. Compruebe espacio, OOM/restarts, permisos de volumen y healthcheck.
4. Confirme que el manifest de imágenes coincide con la release.

Casos comunes:

- `bridge-db`: credenciales/volumen, corrupción o migración; no borre el volumen.
- `bridge-redis`: password, AOF/permisos o memoria; production debe fallar cerrado.
- `bridge-api`: config inválida, DB/Redis no ready o migración pendiente.
- proxies/Portal: archivos tmpfs/permisos UID 101, certificado, upstream o host header.

Escalar antes de cualquier operación destructiva. Un restart repetido puede ocultar evidencia y agravar backlog.

## `/ready` devuelve 503

`/live` solo prueba proceso. `/ready` evalúa dependencias y workers. Revise `/health/details` con cuenta admin y determine DB, Redis, outbox o scheduler. Retire el nodo del tráfico hasta que la causa esté estable; no cambie el healthcheck a `/live`.

## Portal no carga o devuelve 502

- Compruebe TLS proxy → reverse proxy → Portal/Bridge.
- Use el host correcto; el proxy enruta por `PORTAL_HOST`/`API_HOST`.
- Verifique 200 y headers en `/`, `/readyz` y API `/health`.
- Limpie solo caché de la pestaña si el bundle cambió; no exponga tokens en capturas.
- Un stack antiguo en el mismo puerto no es evidencia de la candidata: compruebe proyecto Compose e imagen.

## Login/sesión

- `401`: credenciales incorrectas, expiración, logout, reset o cambio de rol/password.
- Cambio inicial: complete el formulario y vuelva a autenticar; el token previo queda revocado.
- `403`: rol o instalación incorrectos; revise la cuenta, no el código del Portal.
- Muchos intentos: respete la ventana de rate limit; no reinicie Redis para eludirla.

No existe MFA/SSO. Si se sospecha robo de sesión: desactive/resetee usuario, rote secretos si procede, revise auditoría y active respuesta a incidente.

## `409` o `428` en una mutación

- `428 Idempotency-Key`: use un cliente actualizado y una clave estable.
- `428 If-Match`: recargue el recurso y envíe su versión.
- `409 payload diferente`: nunca reutilice la clave para otra operación.
- `409 versión obsoleta`: alguien modificó/decidió el recurso; recargue y revise.
- Timeout después de enviar: consulte el estado y reintente con la **misma** clave.

No modifique directamente tablas de idempotencia/aprobaciones para resolver el conflicto.

## RAG sin resultados o cita incorrecta

1. Verifique documento, estado, ACL y rol.
2. Compruebe que el formato/texto se extrajo; OCR básico puede fallar.
3. Haga una consulta literal con identificadores exactos.
4. Revise límite de corpus/chunks y score mínimo.
5. Si la cita no soporta la respuesta, trate el resultado como fallo y preserve evidencia.

No baje indiscriminadamente el score ni amplíe ACL. Reprocese solo después de conservar el original y documentar la causa.

## SEO no rastrea o landing no aparece fuera

Es comportamiento esperado. SEO analiza HTML suministrado y no hace crawler/fetch. Wiki/landing publican solo localmente tras aprobación. Una ruta pública devuelve 404 mientras el recurso sea borrador/pendiente. La cabecera de landing confirma que no hubo publicación externa.

## Email figura en cola pero no llega

Es comportamiento esperado del core: el spool devuelve `accepted=false`, `queued_for_manual_delivery`. Localice el archivo mediante el procedimiento de administrador, valide permisos/tenant y entréguelo manualmente por el canal aprobado. No cambie el estado a «enviado» sin recibo real.

## Outbox/DLQ crece

- compruebe dependencia destino y credenciales sin exponerlas;
- revise edad, intento y último error;
- corrija la causa y reintente desde la API autorizada con correlación;
- no reinyecte masivamente sin límite ni cambie IDs;
- active incidente si supera el umbral/SLO o afecta acciones críticas.

## Backup/restore falla

- confirme formato 4, manifest, checksums, HMAC y passphrase correcta;
- compruebe `client_id`, perfil y configuración esperados;
- rechace rutas con traversal o artefactos incompletos;
- restaure solo en destino vacío/aislado y conserve el safety backup;
- si falla un check funcional, no promueva ni sobrescriba el origen.

No pruebe contraseñas al azar ni desactive HMAC. El restore integral de la candidata sigue siendo gate pendiente.

## Escalado

Abra incidente si hay fuga entre instalaciones, secreto expuesto, confirmación/pedido duplicado, publicación no aprobada, pérdida/corrupción de datos, facturación inesperada, TLS comprometido, restore fallido o servicio esencial fuera de SLO. Siga [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md).
