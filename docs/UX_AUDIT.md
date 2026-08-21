> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Documento histórico; sus estados, rutas o contratos pueden no corresponder al árbol actual. Consulte `docs/PRODUCTION_READINESS.md` y la documentación canónica homónima de 2026-08-15.

# Auditoría UX actual

## Implementado

- Portal React/TypeScript.
- Español en los recorridos actuales.
- Diseño clean con variables de tema.
- Modo claro y oscuro.
- Login, cambio de contraseña, resumen, integraciones, costes y aprobaciones.
- Datos obtenidos de la API real.
- Sin CDN de React/Babel/Tailwind en producción.

## Pendiente de validación visual

- Build Docker limpio.
- Capturas en 1920×1080, 1366×768, tablet y móvil.
- Navegación completa por teclado.
- Axe/accessibility scan.
- Revisión de todos los estados de error y carga.
- Confirmar que no existe texto visible en inglés.

No se declara la UX validada hasta ejecutar estas pruebas en navegador.
