/**
 * Utilidades puras de formato y navegación del portal.
 *
 * Extraídas de `App.tsx` para que las secciones no dependan del componente
 * raíz. No contienen estado ni efectos secundarios salvo acceso explícito a
 * `localStorage`/`sessionStorage`/`window` donde está documentado.
 */

import { SECTION_IDS, type SectionId } from "./appTypes";

export function formatDate(value: string | null, includeYear = true): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Fecha no disponible";
  return date.toLocaleString("es-ES", {
    day: "2-digit",
    month: "2-digit",
    ...(includeYear ? { year: "numeric" } : {}),
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatNumber(value: number, digits = 2): string {
  return Number.isFinite(value) ? value.toFixed(digits) : "—";
}

export function newIdempotencyKey(): string {
  const uniquePart =
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `portal-product-${uniquePart}`;
}

export function isDemoSource(source: string): boolean {
  return /(^|[_-])(demo|mock|sample|fixture|seed|test)([_-]|$)/i.test(
    source.trim(),
  );
}

export function sectionFromHash(): SectionId {
  const candidate = window.location.hash.replace(/^#/, "") as SectionId;
  // Landing por defecto: el asistente, la superficie única de mando.
  return SECTION_IDS.has(candidate) ? candidate : "asistente";
}

export function clearStoredSession(): void {
  sessionStorage.removeItem("agent_token");
  sessionStorage.removeItem("agent_user");
  sessionStorage.removeItem("agent_role");
  sessionStorage.removeItem("agent_must_change");
}

// Deep-links entre secciones del portal: un enlace (p. ej. el objetivo de
// una decisión del digest) guarda el id del registro a enfocar en
// sessionStorage y navega al hash del módulo. La sección destino consume la
// clave cuando la fila con ese id está en pantalla.
export function consumeFocusId(key: string): string | null {
  const value = sessionStorage.getItem(key);
  if (value) sessionStorage.removeItem(key);
  return value;
}

export function flashFocusRow(element: HTMLElement | null): void {
  if (!element) return;
  element.scrollIntoView({ block: "center", behavior: "smooth" });
  element.classList.add("focus-flash");
  window.setTimeout(() => element.classList.remove("focus-flash"), 2_600);
}

// Intenta enfocar la fila cuyo id está pendiente en ``key``. Devuelve true
// si la encontró y la resaltó; false si aún no está en el DOM (el hook
// destino reintenta en cada cambio de datos y limpia la clave tras 5 s).
export function tryFocusRow(
  key: string,
  selector: (id: string) => string,
): boolean {
  const id = sessionStorage.getItem(key);
  if (!id) return false;
  const el = document.querySelector<HTMLElement>(selector(id));
  if (!el) return false;
  sessionStorage.removeItem(key);
  flashFocusRow(el);
  return true;
}

export function approvalActionLabel(actionType: string): string {
  const labels: Record<string, string> = {
    issue_invoice: "Aprobar borrador de factura",
    confirm_order: "Confirmar pedido",
    publish_landing: "Publicar landing page",
    publish_seo: "Publicar cambio SEO",
    run_automation: "Ejecutar automatización",
    "agent_proposal:create_follow_up":
      "Propuesta del agente CRM: crear follow-up",
    "agent_proposal:dismiss_message":
      "Propuesta del agente social: descartar mensaje",
  };
  return labels[actionType] ?? actionType.replace(/_/g, " ");
}

export function approvalFieldLabel(field: string): string {
  const labels: Record<string, string> = {
    invoice_id: "ID de factura",
    invoice_number: "Número de factura",
    order_id: "ID de pedido",
    amount: "Importe",
    currency: "Moneda",
    agent_id: "Agente",
    module: "Módulo",
    action: "Acción",
    rationale: "Justificación",
    title: "Título de la actividad",
    due_at: "Vencimiento propuesto",
    lead_id: "Lead",
    message_id: "Mensaje social",
    sender: "Remitente",
    body_preview: "Contenido",
    kind_activity: "Tipo de actividad",
  };
  return labels[field] ?? field.replace(/_/g, " ");
}

export function approvalFieldValue(field: string, value: unknown): string {
  if (/password|secret|token|credential|api.?key/i.test(field)) {
    return "Dato protegido";
  }
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (typeof value === "boolean") return value ? "Sí" : "No";
  return "Detalle estructurado disponible en auditoría";
}

export function roleLabel(role: string): string {
  const labels: Record<string, string> = {
    provider_admin: "Administrador de plataforma",
    client_admin: "Administrador del cliente",
    supervisor: "Supervisor",
    commercial: "Comercial",
    support: "Soporte",
    operator: "Operador",
    viewer: "Solo lectura",
  };
  return labels[role] ?? role;
}

export function syncStatusClass(status: string): string {
  switch (status) {
    case "success":
      return "ok";
    case "skipped":
      return "muted";
    case "failed":
      return "error";
    default: // dry_run / conflict
      return "warning";
  }
}

export function syncStatusLabel(status: string): string {
  switch (status) {
    case "success":
      return "Éxito";
    case "dry_run":
      return "Simulación";
    case "conflict":
      return "Conflicto";
    case "skipped":
      return "Omitido";
    case "failed":
      return "Error";
    default:
      return status;
  }
}

export function integrationLabel(name: string): string {
  const labels: Record<string, string> = {
    prestashop: "PrestaShop",
    ghl: "GHL",
    chatwoot: "Chatwoot",
    activepieces: "Activepieces",
  };
  return labels[name] ?? name;
}

export function integrationStatus(state: string): {
  className: string;
  label: string;
} {
  switch (state) {
    case "configured":
      return { className: "ok", label: "Configurado" };
    case "disabled":
      return { className: "muted", label: "Desactivado" };
    case "error":
    case "unavailable":
      return { className: "error", label: "No disponible" };
    default:
      return { className: "warning", label: "Pendiente de configuración" };
  }
}
