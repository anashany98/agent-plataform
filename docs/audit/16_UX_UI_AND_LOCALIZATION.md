> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# 16 - UX, UI y localización

## Alcance y honestidad

- Build producción y TypeScript: VERIFIED.
- Revisión de JSX/CSS/HTML: VERIFIED como lectura.
- Revisión visual real, capturas, teclado y viewports: BLOCKED. RAM > 90 % impidió abrir Chromium.
- El wrapper Playwright incluido en la skill también está desactualizado: `@playwright/mcp 0.0.78` expone `playwright-mcp`, mientras invoca `playwright-cli`; además llegó con CRLF para Bash. No se sustituyó por un método no autorizado.

Por tanto, apariencia, contraste y responsive no se clasifican VERIFIED.

## Función real del portal

El portal implementa:

- Login y cambio obligatorio de contraseña.
- Resumen de cuatro conteos.
- Estado declarado de integraciones.
- Costes.
- Lista/aprobar/rechazar aprobaciones.
- Tema claro/oscuro y logout.

No implementa pantallas de productos, documentos, agentes, automatizaciones o usuarios pese a mostrar enlaces. Esos anchors apuntan a secciones ausentes. El fichero i18n anuncia además conversaciones, clientes, stock, quotes, orders, invoices, SEO, contenidos, backups, alertas e instalaciones que no se renderizan.

## Hallazgos

| Área | Estado | Hallazgo |
|---|---|---|
| Español | PARTIALLY VERIFIED | UI visible en español; strings hardcoded e i18n no usado |
| Build | VERIFIED | 1.470 módulos; bundle sin CDN runtime |
| Claro/oscuro | IMPLEMENTED BUT NOT TESTED | Variables y persistencia local |
| Responsive | IMPLEMENTED BUT NOT TESTED | Breakpoints 1000/760/520; no viewport real |
| Navegación | BROKEN | 5 enlaces principales sin contenido/target útil |
| Loading/error/empty | PARTIALLY VERIFIED | Estados básicos; datos antiguos no se limpian y 401 no desloguea |
| Formularios | PARTIALLY VERIFIED | Labels/autocomplete/minLength; no medidor ni show password |
| Tablas | IMPLEMENTED BUT NOT TESTED | Solo aprobaciones; overflow horizontal |
| Accesibilidad | PARTIALLY VERIFIED | aria en login/iconos y alert role; falta foco visible general/axe/teclado |
| Branding | CONFIGURED ONLY | Marca genérica “AI/Agentes IA”, sin cliente/sector |
| Veracidad | BROKEN | Coste 0 y Activepieces “Configurado” pueden parecer reales; productos demo no se etiquetan |

## Diseño y deuda

- `styles.css` es coherente y compacto, pero usa patrones genéricos de dashboard IA (gradiente azul, glass/backdrop, sidebar).
- `index.css` con Tailwind/glassmorphism está muerto: `main.tsx` no lo importa.
- `i18n/es.ts` está muerto y describe un producto mucho mayor.
- No hay logo/asset/fuente propia; “Inter” cae a fuentes del sistema.
- `CheckCircle2` aparece también en estados pendientes, semánticamente confuso.
- No existe router/deep-link, breadcrumbs, control de permiso por navegación ni confirmación contextual detallada para aprobaciones.
- Rechazo siempre envía el texto fijo “Rechazada desde el panel”.

## Seguridad UX

- Token en `sessionStorage`; correcto frente a persistencia larga, pero legible por XSS.
- Al expirar, el portal muestra error y no fuerza reautenticación.
- Una aprobación muestra payload en el tipo, pero la tabla no enseña importe/detalle suficiente antes de decidir.

## Criterios antes de piloto

1. Ocultar promesas/enlaces no implementados.
2. Etiquetar demo/simulado/no configurado con semántica inequívoca.
3. Añadir detalle y confirmación segura de aprobación.
4. Integrar i18n real o eliminar el catálogo de textos muerto.
5. Ejecutar Playwright/axe en 1440, 1366, 1024, 768 y 375 px, light/dark/teclado.
6. Branding Ofideep y contenido humano revisado.

## Archivos revisados y pendiente

`App.tsx`, CSS, i18n, HTML, Nginx, package/lock y salida build. Las capturas no se fabricaron; quedan BLOCKED hasta liberar recursos y reparar el arnés.
