# Onboarding de cliente

## Regla de entrada

No se conecta un cliente real mientras [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) mantenga `NOT PRODUCTION READY — REMEDIATION INCOMPLETE`. Este documento prepara el onboarding; no sustituye los gates de candidata, restore, carga, seguridad o decisión final.

El alcance recomendado inicial es una instalación por cliente, perfil `production` core, proveedores locales, RAG TF-IDF, publicación local aprobada, email en spool manual, facturas borrador/aprobación interna y sin vendors/egress.

## 1. Descubrimiento y contrato

- [ ] Propietario comercial, técnico, seguridad, privacidad y guardia identificados.
- [ ] Casos de uso, usuarios, volumen, horario, SLO/RPO/RTO y criterios UAT acordados.
- [ ] Datos personales/sensibles, residencia, retención, borrado y legal hold definidos.
- [ ] Módulos incluidos/excluidos firmados.
- [ ] Limitaciones aceptadas: sin crawler/publicación externa, sin delivery email, sin emisión fiscal, sin MFA/SSO, vendors no certificados y token en `sessionStorage`.
- [ ] DPA, licencia del código propio y terceros aprobados.
- [ ] Soporte, severidades, contactos, mantenimiento y salida/offboarding acordados.

## 2. Diseño de la instalación

| Dato | Valor aprobado |
|---|---|
| `CLIENT_ID`/`INSTALLATION_ID` | |
| Proyecto Compose `agent-<id>` | |
| Portal host | |
| API host | |
| Zona/región | |
| RPO / RTO | |
| Ventana de backup | |
| Ventana de mantenimiento | |
| Owner de secretos | |
| Owner de aprobaciones | |
| Owner de spool email | |

El ID debe cumplir el patrón del instalador y no reutilizarse. Reserve DNS, certificado leaf público con ambos SAN, puertos/firewall, volumen de datos y al menos 30 GiB libres de margen operativo.

## 3. Datos y migración

- [ ] Inventario y base legal de cada fuente.
- [ ] Mapeo de clientes, productos, precios, impuestos, stock, leads y documentos.
- [ ] Identificadores/duplicados, encoding, zonas horarias, moneda y decimales.
- [ ] Dataset UAT anonimizado y checksums.
- [ ] Dry-run/import pequeño con recuentos y errores por fila.
- [ ] Reconciliación de totales y muestra dirigida.
- [ ] ACL por rol para documentos RAG.
- [ ] Plan de borrado de temporales y fuentes tras aceptación.

No importar datos reales para «probar si arranca». La migración se realiza después de que el stack limpio y el backup/restore estén demostrados.

## 4. Accesos

- [ ] Dos admins nominales y cuentas operativas por función.
- [ ] `provider_admin` restringido al proveedor autorizado.
- [ ] Matriz RBAC aprobada y pruebas negativas ejecutadas.
- [ ] Contraseñas entregadas por canal seguro y cambio inicial completado.
- [ ] Acceso de red/VPN/allowlist y equipo compartido regulados.
- [ ] Procedimiento de alta, baja, reset y revisión periódica.

## 5. Configuración y release

El release owner debe trabajar desde tag/commit limpio y generar `0.9.1-<sha12>`, manifest, checksums y SBOM. Compose debe propagar `APP_VERSION/RELEASE_VERSION`; preflight/manifiesto rechazan `dev` y valores no SemVer.

Gates mínimos:

- [ ] preflight release PASS con secretos reales y sin warnings no aceptados;
- [ ] build inmutable, labels/commit/version coincidentes;
- [ ] Trivy/SBOM/secret scan finales;
- [ ] seis servicios core healthy/ready con TLS real;
- [ ] base vacía, migración `0013`, sin demo/mocks;
- [ ] aislamiento de red: Bridge solo `internal`+`data`, sin egress;
- [ ] restore integral y rollback ensayados;
- [ ] carga/soak y alert delivery aceptados.

## 6. UAT por módulos

| Área | Casos de aceptación |
|---|---|
| Auth/RBAC | cambio inicial, logout/revocación, todos los roles y negativos |
| Clientes/catálogo | alta idempotente, búsqueda, import y reconciliación |
| Comercio | cálculo, quote, confirmación concurrente, pedido, factura borrador y approval |
| Agentes | allowlist, tool prohibida, provider `none`, budget y activación |
| RAG | ingesta, citas, abstención, ACL, OCR muestra y borrado |
| Wiki/landing | borrador invisible, preview, aprobación y publicación local |
| SEO | HTML local, historial, sin fetch/publicación |
| Tareas/outbox | aprobación, ejecución única, retry, DLQ y restart |
| Lifecycle | export, hold y borrado en sandbox |
| Portal | desktop 1280 y móvil 375/320, teclado, errores y roles |

Cada caso debe guardar resultado esperado/real, usuario/rol, request ID, timestamp, versión e incidencia. Nunca adjunte secretos.

## 7. Go/no-go

Participan Release, QA, Security, SRE, Legal/Privacy, producto y cliente. Se revisan los 30 criterios autoritativos. La decisión debe ser exactamente una de las cuatro permitidas. Cualquier P0, fuga A/B, E2E crítico pendiente, restore no probado, secreto expuesto o build no reproducible produce no-go.

Defina criterios de rollback antes de abrir tráfico: 5xx/SLO, corrupción/duplicado, error de permisos, cola no recuperable, TLS o regresión funcional. Conserve la release anterior y safety backup.

## 8. Activación y acompañamiento

### Día 0

- freeze de cambios, backup verificado y canales abiertos;
- smoke de salud/login/roles/módulos;
- import final/reconciliación;
- tráfico gradual y vigilancia de errores, recursos, backlog y disco;
- registro firmado del go-live o rollback.

### Primeras 24–72 horas

- revisión diaria de accesos, 4xx/5xx/429, outbox, tareas, spool y capacidad;
- muestreo de cálculos, citas y publicaciones;
- cierre/seguimiento de incidencias y comunicación al cliente.

### Día 7 y día 30

- restore drill, revisión RBAC/secretos/certificados;
- SLO/RPO/RTO, uso/coste, retención y feedback;
- confirmar módulos realmente utilizados y retirar datos/cuentas temporales;
- actualizar riesgos, capacidad y plan de mejoras.

## 9. Offboarding

Autorización formal, freeze/export cifrado, entrega con checksum, legal hold, revocación de accesos/secretos, borrado conforme a política, tratamiento de backups y acta de destrucción. Nunca entregue `.env` o backups sin canal y clave separados.
