# Manual de administración

## Responsabilidad y alcance

El administrador controla cuentas, configuración, aprobaciones, datos, backup y operación de una única instalación. Antes de usar datos reales debe confirmar que la decisión de [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) permite el go-live. Un contenedor `healthy` o una suite verde aislada no sustituyen esa decisión.

Nunca habilite el perfil `full`, proveedores externos, facturación automática, egress o publicación externa como solución improvisada. El alcance core certificado se describe en [BUSINESS_MODULES.md](BUSINESS_MODULES.md).

## Primer acceso

1. Reciba por canal seguro el host del Portal y el usuario inicial `admin`.
2. Obtenga la contraseña del recibo local `provision-<client-id>.txt`; no la copie a tickets o chat.
3. Inicie sesión y cambie la contraseña obligatoriamente. El cambio revoca el token y requiere autenticarse de nuevo.
4. Mueva credenciales/secretos al gestor aprobado y elimine el recibo local mediante el procedimiento seguro de la organización.
5. Cree dos cuentas nominales admin como mínimo; no comparta `admin`.
6. Pruebe logout, expiración y recuperación/reset antes del UAT.

La contraseña requiere al menos 12 caracteres, mayúscula, minúscula, número y símbolo. No existe MFA ni SSO: compense con acceso de red restringido, cuentas nominales y revisión de logs.

## Usuarios y roles

En **Usuarios y permisos** puede crear, cambiar rol, desactivar o resetear una cuenta. Toda edición incrementa `token_version` y revoca sesiones anteriores.

- Use `client_admin` para administración del cliente.
- Reserve `provider_admin` para personal autorizado del proveedor.
- Asigne `supervisor`, `commercial`, `support` u `operator` según función real.
- Use `viewer` solo para lectura; no puede ejecutar agentes ni operar comercio.
- Desactive inmediatamente cuentas de baja. El sistema impide que un admin se desactive a sí mismo.

Revise la matriz exacta en [RBAC.md](RBAC.md) y valide casos permitidos/denegados después de cada cambio de versión.

## Salud y diagnóstico diario

Compruebe:

- `/live`: proceso vivo y versión reportada;
- `/health`: estado público mínimo sin detalles internos;
- `/ready`: DB, Redis, outbox y scheduler aptos para tráfico;
- `/health/details` y `/metrics`: solo admin, para diagnóstico;
- panel de integraciones y backlog/edad de outbox;
- espacio de disco, reinicios, CPU/RAM y certificados TLS.

Registre correlation/request ID, hora UTC, versión y módulo al escalar. No adjunte tokens, passwords, `.env`, dumps o documentos del cliente.

## Catálogo, CRM e importación

El core usa catálogo y CRM locales. Para una importación:

1. valide mapeo, encoding, moneda, IVA, IDs externos y tratamiento de duplicados;
2. pruebe con una copia pequeña/no sensible;
3. use una `Idempotency-Key` estable;
4. revise errores por fila y recuentos;
5. reconcilie muestras, precios, stock y búsqueda;
6. conserve el archivo de origen conforme a la política de datos.

PrestaShop y GHL son opcionales y no forman parte del gate core. No configure sus secretos ni egress sin certificación independiente.

## Documentos y RAG

Solo admins ingieren, suben o eliminan documentos. Defina los roles autorizados en la ACL antes de subir. No incluya secretos ni datos fuera del contrato. El límite por defecto es 25 MiB; PDF/OCR complejo requiere control visual.

Tras cada ingesta:

1. compruebe nombre, tamaño y ACL;
2. formule preguntas de identificadores y hechos exactos;
3. valide que las citas apuntan al fragmento correcto;
4. pruebe un rol sin permiso y una instalación distinta;
5. pruebe una pregunta sin evidencia, que debe abstenerse o mostrar insuficiencia.

TF-IDF local es recuperación léxica, no comprensión universal. Tesseract es OCR básico y no sustituye revisión humana.

## Agentes

Al crear un agente, aplique la allowlist mínima. Las únicas tools registradas son búsquedas/lecturas, cálculo determinista, RAG y creación de presupuesto borrador. Un nombre no registrado no otorga permiso.

Flujo:

1. crear/editar definición;
2. revisar instrucciones, nivel/modelo, presupuesto y tools;
3. solicitar activación con la versión actual;
4. un admin revisa la aprobación;
5. ejecutar casos nominales, prompt injection, tool prohibida y falta de proveedor;
6. desactivar/rechazar ante cualquier conducta no prevista.

En core, los proveedores generativos están en `none`; no prometa respuesta LLM si no se ha certificado un proveedor.

## Aprobaciones

La cola contiene solicitudes versionadas. Antes de aprobar:

- confirme solicitante, tipo, target y versión;
- compare preview/datos con la fuente;
- rechace si el recurso cambió o la evidencia es incompleta;
- escriba una razón útil al rechazar;
- no autoapruebe salvo política expresa y emergencia registrada.

La concurrencia puede devolver `409`; recargue y no fuerce una decisión antigua. `approved` en una factura es aprobación interna, no emisión fiscal.

## Wiki, SEO y landing

Wiki y landing trabajan con borrador/preview/aprobación y solo publican localmente. Revise contenido, enlaces, datos personales y preview antes de aprobar. El backend usa allowlist/escaping y CSP, pero la revisión editorial sigue siendo obligatoria.

SEO analiza únicamente HTML suministrado. No rastrea la web ni publica cambios. Archive el HTML fuente y el resultado para trazabilidad; no interprete el historial como monitorización externa.

## Tareas y automatizaciones

El único `task_type` certificado es `automation_sweep`, con intervalo entre 60 segundos y 30 días. La activación requiere aprobación. Evite solapar tareas con backups/importaciones y vigile outbox/DLQ.

Activepieces/FlowWink no están certificados para el core. Un trigger con timeout debe reconciliarse y reintentarse con la misma clave.

## Email local

El proveedor core crea un archivo JSON por instalación y devuelve `accepted=false`, `queued_for_manual_delivery`. Establezca un responsable para retirar, revisar, entregar por canal aprobado y borrar conforme a retención. El dashboard no puede afirmar «enviado».

## Ciclo de vida y privacidad

Configure retención conforme al contrato (30 días por defecto, máximo técnico 365). Antes de exportar, borrar o aplicar legal hold, verifique identidad, autoridad, alcance y ticket. El borrado puede ser diferido; documente la fecha efectiva y su efecto sobre backups según política.

## Backup, actualización y rollback

Siga exclusivamente [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md) y [UPGRADE_AND_ROLLBACK.md](UPGRADE_AND_ROLLBACK.md). Use un checkout dedicado, passphrase desde secreto temporal y artefactos con manifest/HMAC/checksums. Nunca pruebe restore sobre la instalación única ni ejecute update/rollback desde el checkout compartido de desarrollo.

Un restore integral final sigue pendiente hasta que la candidata lo demuestre. Antes de cada cambio: preflight, backup de seguridad, ventana, criterio de abort, observador y canal de incidente.

## Rutina recomendada

### Diaria

- readiness, TLS, espacio, errores 5xx, 429 y backlog;
- tareas fallidas/DLQ y archivos email pendientes;
- aprobaciones antiguas y cuentas anómalas.

### Semanal

- restore de muestra en entorno aislado;
- revisión de usuarios/roles, logs, consumo y capacidad;
- expiración de secretos/certificados y retención.

### Mensual

- restore integral/DR según política;
- parches, dependencias, SBOM y licencias;
- SLO/capacidad, incidentes y revisión de accesos.
