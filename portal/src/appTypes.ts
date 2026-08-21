/**
 * Tipos y constantes compartidos del portal.
 *
 * Extraídos de `App.tsx` para que cada sección importe solo lo que usa y el
 * componente raíz deje de concentrar las definiciones de dominio.
 */

export type Approval = {
  id: string;
  action_type: string;
  target_key: string;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
  /** Labels en lenguaje llano que el backend añade desde la v2 (opcionales
   * para instalaciones antiguas o mocks de test). */
  action_label?: string;
  target_label?: string;
};

export type ApprovalIntent = {
  approval: Approval;
  decision: "approve" | "reject";
};

export type DashboardPermissions = {
  approve: boolean;
  manage_leads: boolean;
  manage_users: boolean;
  view_costs: boolean;
  import_catalog: boolean;
};

export type Dashboard = {
  installation_id: string;
  installed_version: string;
  pilot_mode: boolean;
  role: string;
  permissions: DashboardPermissions;
  integrations: Record<string, string>;
  counts: Record<string, number>;
};

export type LeadOpportunity = {
  id: string;
  name: string;
  stage: string;
  status: string;
  monetary_value: number;
  currency: string;
  external_reference: string | null;
  notes_count: number;
  created_at: string | null;
};

export type LeadRow = {
  id: string;
  email: string;
  first_name: string;
  phone: string | null;
  company_name: string | null;
  source: string;
  status: string;
  created_at: string | null;
  opportunities: LeadOpportunity[];
};

export type CostSummary = {
  total_executions: number;
  total_tokens_consumed: number;
  total_estimated_cost_usd: number;
  avg_latency_ms: number;
  simulated_executions: number;
};

export type SyncHistoryRow = {
  id: string;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  since: string | null;
  incremental: boolean;
  status: string;
  total_remote: number;
  created: number;
  updated: number;
  unchanged: number;
  error: string | null;
};

export type ProductRow = {
  id: string;
  sku: string;
  name: string;
  category: string;
  unit_price: number;
  tax_rate: number;
  available_stock: number;
  source: string;
  updated_at: string | null;
};

export type SemanticProductRow = ProductRow & {
  score: number;
};

export type DocumentRow = {
  id: string;
  file_name: string;
  mime_type: string | null;
  classification: string;
  dlp_findings: string[];
  created_at: string | null;
};

export type UserRow = {
  id: string;
  username: string;
  role: string;
  is_active: boolean;
  must_change_password: boolean;
};

export type ImportResponse = {
  status: string;
  valid_rows?: number;
  invalid_rows?: number;
  imported_count?: number;
  errors?: Array<{ row: number; error: string }>;
};

export type SectionId =
  | "asistente"
  | "resumen"
  | "aprobaciones"
  | "catalogo"
  | "documentos"
  | "agentes"
  | "clientes"
  | "ventas"
  | "contenido"
  | "tareas"
  | "automatizaciones"
  | "usuarios"
  | "webhooks"
  | "email";

export const SECTION_IDS = new Set<SectionId>([
  "asistente",
  "resumen",
  "aprobaciones",
  "catalogo",
  "documentos",
  "agentes",
  "clientes",
  "ventas",
  "contenido",
  "tareas",
  "automatizaciones",
  "usuarios",
  "webhooks",
  "email",
]);

export const SECTION_TITLES: Record<SectionId, string> = {
  asistente: "Asistente",
  resumen: "Hoy",
  aprobaciones: "Aprobaciones pendientes",
  catalogo: "Productos",
  documentos: "Documentos",
  agentes: "Agentes de IA",
  clientes: "Clientes",
  ventas: "Ventas y facturación",
  contenido: "Contenido, SEO y landings",
  tareas: "Tareas programadas",
  automatizaciones: "Automatizaciones",
  usuarios: "Usuarios y permisos",
  webhooks: "Webhooks salientes",
  email: "Email integrado",
};

// Menú lateral agrupado por intención (no por módulo técnico): una persona sin
// experiencia encuentra cada sección por lo que quiere hacer, no por el nombre
// del componente. Los grupos sin secciones permitidas por el rol se ocultan.
export type NavGroupId =
  "inicio" | "ventas" | "catalogo" | "marketing" | "ajustes";

export const NAV_GROUP_LABELS: Record<NavGroupId, string> = {
  inicio: "Inicio",
  ventas: "Ventas",
  catalogo: "Catálogo",
  marketing: "Marketing",
  ajustes: "Ajustes",
};

export const NAV_GROUP_ORDER: NavGroupId[] = [
  "inicio",
  "ventas",
  "catalogo",
  "marketing",
  "ajustes",
];

export const ADMIN_ROLES = new Set(["provider_admin", "client_admin"]);
export const DEFAULT_ACCENT = "#246bfd";
export const ACCENT_PRESETS = [
  "#246bfd",
  "#0ea271",
  "#7c5cf0",
  "#d97706",
  "#e11d48",
  "#0d9488",
  "#db2777",
  "#475569",
];
export const OPERATOR_ROLES = new Set([
  ...ADMIN_ROLES,
  "supervisor",
  "commercial",
  "support",
  "operator",
]);

// Secciones técnicas que el «modo simple» oculta por defecto: una persona sin
// experiencia no las necesita para operar el día a día (productos, ventas,
// aprobaciones y automatizaciones). El modo avanzado las revela sin cambiar
// el RBAC. Automatizaciones quedó FUERA porque el panel ya es el motor
// amigable y accionable (estado, «Ejecutar ahora» y cola de reintentos), y la
// pantalla «Hoy» enlaza sus fallos directamente a ese panel.
export const ADVANCED_SECTIONS = new Set<SectionId>([
  "documentos",
  "agentes",
  "contenido",
  "tareas",
  "usuarios",
  "webhooks",
  "email",
]);
