# Audit UX/UI y Localización — AI Agent Enterprise Platform

**Fecha:** 2026-07-31  
**Objetivo:** Transición de MVP a **`COMMERCIAL PILOT READY — FIRST CLIENT DEPLOYMENT VERIFIED`**  
**Criterio de Calidad:** Diseño SaaS empresarial premium (estilo Apple/macOS/iOS), 100% en español, sin aspecto de plantilla genérica ni texto en inglés.

---

## 1. Auditoría de Textos en Inglés (Localización Pendiente)

| Ubicación Actual | Texto en Inglés Detectado | Traducción / Adaptación Profesional (Español) | Estado |
|---|---|---|---|
| Navigation Header | `Agent Platform` | Configurable por cliente (ej. *Plataforma de Agentes IA*) | Pendiente |
| Navigation Header | `Internal MVP v2.0` | *Edición Empresarial v2.0* | Pendiente |
| Status Badge | `Bridge API Healthy (:8005)` | *Sistema Operativo* (Detalles al pulsar) | Pendiente |
| Navigation Sidebar | `Dashboard` | **Resumen** | Pendiente |
| Navigation Sidebar | `Panel del Proveedor` | **Proveedor** | Pendiente |
| Navigation Sidebar | `Agentes IA` | **Agentes de IA** | Pendiente |
| Navigation Sidebar | `Approvals` | **Aprobaciones** | Pendiente |
| Navigation Sidebar | `Products & Stock` | **Productos y Existencias** | Pendiente |
| Navigation Sidebar | `Documentos RAG` | **Base de Conocimiento** (*Documentos*) | Pendiente |
| Navigation Sidebar | `Costes & Tokens` | **Consumo y Costes** | Pendiente |
| Navigation Sidebar | `Integrations` | **Integraciones** | Pendiente |
| Status Matrix | `Service`, `Healthy`, `UP` | *Servicio*, *Operativo*, *Activo* | Pendiente |
| Provider Panel | `Client Name`, `Domain`, `Version` | *Cliente*, *Dominio*, *Versión Instalada* | Pendiente |
| Action Buttons | `Submit`, `Save`, `Cancel`, `Delete` | *Enviar*, *Guardar*, *Cancelar*, *Eliminar* | Pendiente |

---

## 2. Auditoría Visual y Estructura del Layout

### Problemas Visuales Identificados:
1. **Panel del Proveedor:** En el prototipo inicial solo mostraba 3 tarjetas con un enorme espacio vacío. Necesita el rediseño completo empresarial con: Resumen Ejecutivo, Tabla de Instalaciones, Salud de Servicios, Alerta de Incidencias, Control de Versiones y Copias de Seguridad.
2. **Jerarquía Visual:** Faltan breadcrumbs superiores, el indicador técnico `(:8005)` debe reemplazarse por un widget discreto de estado general (*Todo operativo*, *Incidencias*).
3. **Agrupación de Menú Lateral:** El menú actual es plano. Debe estructurarse en 5 grupos semánticos:
   - **INICIO** (Resumen)
   - **OPERACIONES** (Conversaciones, Agentes, Aprobaciones, Clientes, Productos, Existencias, Presupuestos, Pedidos, Facturas)
   - **CONOCIMIENTO Y CRECIMIENTO** (Documentos, Base de Conocimiento, SEO, Contenidos, Automatizaciones)
   - **CONTROL** (Integraciones, Consumo y Costes, Usuarios, Auditoría, Configuración)
   - **PROVEEDOR** (Clientes, Instalaciones, Salud, Versiones, Copias, Alertas) — *Solo visibles para rol Proveedor*.
4. **Modo Piloto:** Implementar la bandera `PILOT_MODE=true` con banner superior sutil ("Modo Piloto Activo — Borradores y Aprobaciones Obligatorias").
5. **Branding Configurable por Cliente:** Soporte para nombre de empresa, marca, logotipo, favicon y color de acento.

---

## 3. Plan de Rediseño de Componentes
- Crear sistema i18n centralizado en `portal/src/i18n/es.ts`.
- Rediseñar `portal/src/App.tsx` y `portal/index.html` con sistema Glassmorphic/macOS sobrio, tipografía Inter/system-ui, drawer responsive y modo claro/oscuro.
