# Gestión de secretos

## Alcance

Incluye contraseñas PostgreSQL/Redis, `AUTH_SECRET`, credenciales iniciales, claves HMAC/webhook, tokens/API keys, cifrado Activepieces, passphrase de backup y clave privada TLS.

## Reglas

1. Un juego de secretos por cliente y entorno; nunca copiar producción a desarrollo.
2. No escribir secretos en Git, documentación, tickets, chat, logs, screenshots, manifests o nombres de archivo.
3. `.env.<cliente>` y archivos TLS quedan fuera de Git y con permisos mínimos; en Linux, 0600.
4. Generar con CSPRNG; cumplir los mínimos del preflight: PostgreSQL/Redis ≥24, auth ≥32, admin ≥16 y política de contraseña.
5. `SOURCE_COMMIT`, image IDs, key IDs y fechas de rotación pueden registrarse; el valor secreto no.
6. La passphrase de backup se pasa por entorno temporal `BACKUP_ENCRYPTION_PASSPHRASE` y no se guarda junto al backup.
7. El manifest de release no contiene secretos; el backup sí incluye la configuración cifrada y debe custodiarse como secreto.

## Inventario y propietario

| Secreto | Consumidor | Rotación mínima sugerida | Evento de rotación inmediata |
|---|---|---|---|
| `POSTGRES_PASSWORD` | Bridge/DB | 180 días | host/backup/env expuesto |
| `REDIS_PASSWORD` | Bridge/Redis | 180 días | host/env expuesto |
| `AUTH_SECRET` | Bridge | 90 días | token o env expuesto; revoca sesiones |
| `INITIAL_ADMIN_PASSWORD` | Bootstrap | Inmediata tras primer login | siempre; nunca conservar temporal |
| Webhook HMAC/outbound | Bridge/integración | 90 días | replay/firma anómala/exposición |
| API keys externas | Adaptadores | Según proveedor, máx. 90 días | exposición/cambio de operador |
| TLS private key | tls-proxy | Renovación cert/política CA | compromiso del host/clave |
| Backup passphrase | Operación | 90 días con versionado | backup/host/custodio comprometido |

La cadencia debe ajustarse al contrato y al secret manager elegido; la tabla no es certificación de cumplimiento.

## Provisionamiento

1. Copiar `.env.example` a `.env.<cliente>` sin sobrescribir un archivo existente.
2. Generar valores localmente; no pegarlos en la conversación de soporte.
3. Emitir certificado leaf público con SAN de `PORTAL_HOST` y `API_HOST`.
4. Guardar los secrets en vault/gestor aprobado y materializarlos solo durante despliegue.
5. Ejecutar:

```powershell
python scripts/production-preflight.py --env-file .env.<cliente> --profile production --mode release
```

6. Cambiar la contraseña temporal en el primer login y comprobar que la anterior falla.

## Rotación sin pérdida

- Preparar backup y ventana.
- Rotar primero en la autoridad (DB/Redis/proveedor), luego actualizar consumidores y recrear el mínimo servicio.
- Para HMAC con zero-downtime se necesita soporte de dos key IDs; si no existe, coordinar una pausa breve.
- Rotar `AUTH_SECRET` invalida todos los JWT: comunicar re-login.
- Tras rotar, ejecutar readiness/smoke y buscar autenticaciones con el secreto antiguo.
- Registrar quién, cuándo, qué key ID/version y resultado; nunca el valor.

## Detección

- Escanear árbol, historia, artefactos, imágenes y logs antes de release.
- Un hallazgo real obliga a revocar; borrar del último commit no neutraliza una credencial.
- No usar tokens de ejemplo, dominios reales con credenciales o backups reales en tests.

## Secretos de vendors

El perfil `production` core no los requiere. `full` utiliza un inventario separado y no debe compartir claves Bridge. Chatwoot Enterprise, Activepieces y servicios SaaS requieren revisión legal/seguridad antes de provisionar.
