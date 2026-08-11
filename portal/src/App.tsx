import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  Boxes,
  CheckCircle2,
  FileText,
  Gauge,
  LogOut,
  Moon,
  Package,
  RefreshCw,
  ShieldCheck,
  Sun,
  Users,
  Workflow,
} from "lucide-react";
import { translations } from "./i18n/es";

type Approval = {
  id: string;
  action_type: string;
  target_key: string;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
};

type DashboardPermissions = {
  approve: boolean;
  manage_leads: boolean;
  manage_users: boolean;
  view_costs: boolean;
  import_catalog: boolean;
};

type Dashboard = {
  installation_id: string;
  installed_version: string;
  pilot_mode: boolean;
  role: string;
  permissions: DashboardPermissions;
  integrations: Record<string, string>;
  counts: Record<string, number>;
};

type LeadOpportunity = {
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

type LeadRow = {
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

type CostSummary = {
  total_executions: number;
  total_tokens_consumed: number;
  total_estimated_cost_usd: number;
  avg_latency_ms: number;
  simulated_executions: number;
};

type ProductRow = {
  id: string;
  sku: string;
  name: string;
  category: string;
  unit_price: number;
  tax_rate: number;
  available_stock: number;
  source: string;
};

type DocumentRow = {
  id: string;
  file_name: string;
  mime_type: string | null;
  classification: string;
  dlp_findings: string[];
  created_at: string | null;
};

type AgentRow = {
  agent_id: string;
  name: string;
  purpose: string;
  status?: string;
};

type UserRow = {
  id: string;
  username: string;
  role: string;
  is_active: boolean;
  must_change_password: boolean;
};

type SectionId =
  | "resumen"
  | "aprobaciones"
  | "catalogo"
  | "documentos"
  | "agentes"
  | "clientes"
  | "automatizaciones"
  | "usuarios";

const ADMIN_ROLES = new Set(["provider_admin", "client_admin"]);
const OPERATOR_ROLES = new Set([
  "provider_admin",
  "client_admin",
  "supervisor",
  "commercial",
  "support",
  "operator",
]);

const API_BASE = "/api/bridge";

async function api<T>(
  path: string,
  token: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : "No se pudo completar la operación";
    throw new Error(detail);
  }
  return data as T;
}

function Login({
  onLogin,
}: {
  onLogin: (
    token: string,
    username: string,
    role: string,
    mustChangePassword: boolean,
  ) => void;
}) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(data.detail ?? "No se pudo iniciar sesión");
      onLogin(
        data.access_token,
        data.username,
        data.role ?? "",
        Boolean(data.must_change_password),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error inesperado");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-card" aria-labelledby="login-title">
        <div className="brand-mark">AI</div>
        <h1 id="login-title">Plataforma de agentes IA</h1>
        <p>Accede al panel de control de tu instalación.</p>
        <form onSubmit={submit}>
          <label>
            Usuario
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>
            Contraseña
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          <button className="primary-button" disabled={loading}>
            {loading ? "Accediendo…" : "Acceder"}
          </button>
        </form>
      </section>
    </main>
  );
}

function ChangePassword({
  token,
  onComplete,
  onLogout,
}: {
  token: string;
  onComplete: () => void;
  onLogout: () => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (newPassword !== confirmation) {
      setError("Las contraseñas nuevas no coinciden");
      return;
    }
    setLoading(true);
    try {
      await api("/auth/change-password", token, {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      onComplete();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudo cambiar la contraseña",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-card" aria-labelledby="password-title">
        <div className="brand-mark">AI</div>
        <h1 id="password-title">Cambia la contraseña temporal</h1>
        <p>
          Por seguridad, debes crear una contraseña personal antes de acceder al
          panel.
        </p>
        <form onSubmit={submit}>
          <label>
            Contraseña temporal
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <label>
            Nueva contraseña
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              minLength={12}
              required
            />
          </label>
          <label>
            Repite la nueva contraseña
            <input
              type="password"
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              autoComplete="new-password"
              minLength={12}
              required
            />
          </label>
          <p className="password-help">
            Mínimo 12 caracteres, con mayúscula, minúscula, número y símbolo.
          </p>
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          <button className="primary-button" disabled={loading}>
            {loading ? "Guardando…" : "Cambiar contraseña"}
          </button>
          <button
            type="button"
            className="secondary-button full-width"
            onClick={onLogout}
          >
            Volver al acceso
          </button>
        </form>
      </section>
    </main>
  );
}

function ProductsSection({
  token,
  canImport,
}: {
  token: string;
  canImport: boolean;
}) {
  const [rows, setRows] = useState<ProductRow[] | null>(null);
  const [error, setError] = useState("");
  const [importForm, setImportForm] = useState({
    sku: "",
    name: "",
    category: "Industrial",
    base_price: "0.00",
    stock_quantity: "0",
  });
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState("");

  async function importProduct(event: FormEvent) {
    event.preventDefault();
    setImporting(true);
    setImportResult("");
    try {
      const result = await api<{ status: string; created?: number }>(
        "/import/products",
        token,
        {
          method: "POST",
          body: JSON.stringify({
            items: [
              {
                sku: importForm.sku.trim(),
                name: importForm.name.trim(),
                category: importForm.category.trim(),
                base_price: Number(importForm.base_price),
                tax_rate: 0.21,
                stock_quantity: Number(importForm.stock_quantity),
                source: "local",
              },
            ],
            dry_run: false,
          }),
        },
      );
      setImportResult(
        `Importado: ${result.status}${result.created != null ? ` (${result.created} productos)` : ""}`,
      );
      setImportForm({
        sku: "",
        name: "",
        category: "Industrial",
        base_price: "0.00",
        stock_quantity: "0",
      });
      const data = await api<ProductRow[]>("/tools/products", token);
      setRows(data);
    } catch (err) {
      setImportResult(
        err instanceof Error ? err.message : "No se pudo importar",
      );
    } finally {
      setImporting(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    api<ProductRow[]>("/tools/products", token)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error
              ? err.message
              : "No se pudo cargar el catálogo",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <section id="catalogo" className="panel" aria-label="Catálogo de productos">
      <div className="panel-heading">
        <div>
          <p>Catálogo</p>
          <h2>Productos</h2>
        </div>
        <span className="counter">{rows?.length ?? 0}</span>
      </div>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {!error && rows === null && (
        <div className="empty-state">Cargando catálogo…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="empty-state">
          No hay productos disponibles en esta instalación.
        </div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Nombre</th>
                <th>SKU</th>
                <th>Categoría</th>
                <th>Precio unitario</th>
                <th>Stock disponible</th>
                <th>Origen</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.name}</td>
                  <td>{row.sku}</td>
                  <td>{row.category || "—"}</td>
                  <td>{row.unit_price.toFixed(2)} €</td>
                  <td>{row.available_stock}</td>
                  <td>{row.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {canImport && (
        <form
          className="import-form"
          onSubmit={(event) => void importProduct(event)}
          aria-label="Importar producto"
        >
          <p>Importar producto al catálogo local</p>
          <div className="import-grid">
            <label>
              SKU
              <input
                value={importForm.sku}
                onChange={(e) =>
                  setImportForm({ ...importForm, sku: e.target.value })
                }
                required
              />
            </label>
            <label>
              Nombre
              <input
                value={importForm.name}
                onChange={(e) =>
                  setImportForm({ ...importForm, name: e.target.value })
                }
                required
              />
            </label>
            <label>
              Categoría
              <input
                value={importForm.category}
                onChange={(e) =>
                  setImportForm({ ...importForm, category: e.target.value })
                }
              />
            </label>
            <label>
              Precio unitario
              <input
                type="number"
                step="0.01"
                min="0"
                value={importForm.base_price}
                onChange={(e) =>
                  setImportForm({ ...importForm, base_price: e.target.value })
                }
                required
              />
            </label>
            <label>
              Stock
              <input
                type="number"
                min="0"
                value={importForm.stock_quantity}
                onChange={(e) =>
                  setImportForm({
                    ...importForm,
                    stock_quantity: e.target.value,
                  })
                }
                required
              />
            </label>
            <button className="primary-button" disabled={importing}>
              {importing ? "Importando…" : "Importar"}
            </button>
          </div>
          {importResult && (
            <div className="alert info" role="status">
              {importResult}
            </div>
          )}
        </form>
      )}
    </section>
  );
}

function LeadsSection({ token }: { token: string }) {
  const [rows, setRows] = useState<LeadRow[] | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    email: "",
    first_name: "",
    phone: "",
    company_name: "",
  });
  const [creating, setCreating] = useState(false);
  const [createResult, setCreateResult] = useState("");

  async function loadLeads() {
    try {
      setRows(await api<LeadRow[]>("/leads", token));
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudieron cargar los leads",
      );
    }
  }

  useEffect(() => {
    void loadLeads();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function createLead(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setCreateResult("");
    try {
      await api("/leads", token, {
        method: "POST",
        body: JSON.stringify({
          email: form.email.trim(),
          first_name: form.first_name.trim(),
          phone: form.phone.trim() || null,
          company_name: form.company_name.trim() || null,
        }),
      });
      setCreateResult("Lead creado");
      setForm({ email: "", first_name: "", phone: "", company_name: "" });
      await loadLeads();
    } catch (err) {
      setCreateResult(
        err instanceof Error ? err.message : "No se pudo crear el lead",
      );
    } finally {
      setCreating(false);
    }
  }

  return (
    <section
      id="clientes"
      className="panel"
      aria-label="Clientes y oportunidades"
    >
      <div className="panel-heading">
        <div>
          <p>CRM local</p>
          <h2>Leads y oportunidades</h2>
        </div>
        <span className="counter">{rows?.length ?? 0}</span>
      </div>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {!error && rows === null && (
        <div className="empty-state">Cargando leads…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="empty-state">
          No hay leads en esta instalación. Crea el primero con el formulario.
        </div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Cliente</th>
                <th>Email</th>
                <th>Oportunidades</th>
                <th>Estado</th>
                <th>Alta</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((lead) => (
                <tr key={lead.id}>
                  <td>
                    {lead.first_name}
                    {lead.company_name ? ` (${lead.company_name})` : ""}
                  </td>
                  <td>{lead.email}</td>
                  <td>
                    {lead.opportunities.length === 0
                      ? "—"
                      : lead.opportunities
                          .map(
                            (opp) =>
                              `${opp.name} · ${opp.monetary_value.toFixed(2)} ${opp.currency}`,
                          )
                          .join(" / ")}
                  </td>
                  <td>{lead.status}</td>
                  <td>
                    {lead.created_at
                      ? new Date(lead.created_at).toLocaleString("es-ES")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form
        className="import-form"
        onSubmit={(event) => void createLead(event)}
        aria-label="Nuevo lead"
      >
        <p>Nuevo lead</p>
        <div className="import-grid">
          <label>
            Email
            <input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              required
            />
          </label>
          <label>
            Nombre
            <input
              value={form.first_name}
              onChange={(e) => setForm({ ...form, first_name: e.target.value })}
              required
            />
          </label>
          <label>
            Teléfono
            <input
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
            />
          </label>
          <label>
            Empresa
            <input
              value={form.company_name}
              onChange={(e) =>
                setForm({ ...form, company_name: e.target.value })
              }
            />
          </label>
          <button className="primary-button" disabled={creating}>
            {creating ? "Creando…" : "Crear lead"}
          </button>
        </div>
        {createResult && (
          <div className="alert info" role="status">
            {createResult}
          </div>
        )}
      </form>
    </section>
  );
}

function DocumentsSection({ token }: { token: string }) {
  const [rows, setRows] = useState<DocumentRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api<{ documents: DocumentRow[] }>("/rag/documents", token)
      .then((data) => {
        if (!cancelled) setRows(data.documents);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error
              ? err.message
              : "No se pudieron cargar los documentos",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <section id="documentos" className="panel" aria-label="Documentos RAG">
      <div className="panel-heading">
        <div>
          <p>Conocimiento</p>
          <h2>Documentos</h2>
        </div>
        <span className="counter">{rows?.length ?? 0}</span>
      </div>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {!error && rows === null && (
        <div className="empty-state">Cargando documentos…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="empty-state">
          No hay documentos indexados en esta instalación.
        </div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Archivo</th>
                <th>Clasificación</th>
                <th>Hallazgos DLP</th>
                <th>Alta</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.file_name}</td>
                  <td>{row.classification}</td>
                  <td>
                    {row.dlp_findings.length > 0
                      ? row.dlp_findings.join(", ")
                      : "—"}
                  </td>
                  <td>
                    {row.created_at
                      ? new Date(row.created_at).toLocaleString("es-ES")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function AgentsSection({ token }: { token: string }) {
  const [rows, setRows] = useState<AgentRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api<{ agents: AgentRow[] }>("/agents", token)
      .then((data) => {
        if (!cancelled) setRows(data.agents);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error
              ? err.message
              : "No se pudieron cargar los agentes",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <section id="agentes" className="panel" aria-label="Agentes de IA">
      <div className="panel-heading">
        <div>
          <p>IA</p>
          <h2>Agentes de IA</h2>
        </div>
        <span className="counter">{rows?.length ?? 0}</span>
      </div>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {!error && rows === null && (
        <div className="empty-state">Cargando agentes…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="empty-state">
          No hay agentes registrados en esta instalación.
        </div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Agente</th>
                <th>Propósito</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.agent_id}>
                  <td>{row.name}</td>
                  <td>{row.purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function UsersSection({ token }: { token: string }) {
  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api<UserRow[]>("/users", token)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error
              ? err.message
              : "No se pudieron cargar los usuarios",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <section id="usuarios" className="panel" aria-label="Usuarios y permisos">
      <div className="panel-heading">
        <div>
          <p>Control de acceso</p>
          <h2>Usuarios y permisos</h2>
        </div>
        <span className="counter">{rows?.length ?? 0}</span>
      </div>
      {error && (
        <div className="alert error" role="alert">
          {error}. Esta sección requiere rol administrador.
        </div>
      )}
      {!error && rows === null && (
        <div className="empty-state">Cargando usuarios…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="empty-state">No hay usuarios registrados.</div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Usuario</th>
                <th>Rol</th>
                <th>Activo</th>
                <th>Cambio de contraseña pendiente</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.username}</td>
                  <td>{row.role}</td>
                  <td>{row.is_active ? "Sí" : "No"}</td>
                  <td>{row.must_change_password ? "Sí" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function AutomationsSection({ dashboard }: { dashboard: Dashboard | null }) {
  const activepieces = dashboard?.integrations?.activepieces;
  return (
    <section
      id="automatizaciones"
      className="panel"
      aria-label="Automatizaciones"
    >
      <div className="panel-heading">
        <div>
          <p>Flujos</p>
          <h2>Automatizaciones</h2>
        </div>
        <Workflow size={21} />
      </div>
      <div className="integration-list">
        <div className="integration-row">
          <span>Activepieces</span>
          <span
            className={`status ${activepieces === "configured" ? "ok" : "warning"}`}
          >
            <CheckCircle2 size={14} />
            {activepieces === "configured"
              ? "Configurado"
              : "Pendiente de configuración"}
          </span>
        </div>
      </div>
      <div className="empty-state">
        El diseñador de automatizaciones no forma parte de la candidata core
        (Ruta A). Los flujos se ejecutan a través del bridge con validación,
        auditoría y aprobaciones; consulta la documentación de integraciones
        para habilitar Activepieces.
      </div>
    </section>
  );
}

export default function App() {
  const [token, setToken] = useState(
    () => sessionStorage.getItem("agent_token") ?? "",
  );
  const [username, setUsername] = useState(
    () => sessionStorage.getItem("agent_user") ?? "",
  );
  const [role, setRole] = useState(
    () => sessionStorage.getItem("agent_role") ?? "",
  );
  const [mustChangePassword, setMustChangePassword] = useState(
    () => sessionStorage.getItem("agent_must_change") === "true",
  );
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [costs, setCosts] = useState<CostSummary | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [approvalsError, setApprovalsError] = useState("");
  const [costsError, setCostsError] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [section, setSection] = useState<SectionId>("resumen");
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("theme") as "light" | "dark") ?? "light",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  // RBAC: el backend es la autoridad (/dashboard expone permissions); el
  // fallback por rol solo se usa mientras el dashboard no ha cargado (T-024).
  const permissions = dashboard?.permissions ?? {
    approve: OPERATOR_ROLES.has(role),
    manage_leads: OPERATOR_ROLES.has(role),
    manage_users: ADMIN_ROLES.has(role),
    view_costs: ADMIN_ROLES.has(role),
    import_catalog: ADMIN_ROLES.has(role),
  };

  // Carga parcial por rol: cada bloque es independiente y un 403 nunca
  // tumba el resto del panel (antes Promise.all hacía fallar todo el load).
  async function load() {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const dashboardData = await api<Dashboard>("/dashboard", token);
      setDashboard(dashboardData);
      const perms = dashboardData.permissions;
      if (perms.approve) {
        try {
          setApprovals(
            await api<Approval[]>("/approvals?status_filter=pending", token),
          );
          setApprovalsError("");
        } catch (err) {
          setApprovals([]);
          setApprovalsError(
            err instanceof Error
              ? err.message
              : "No se pudieron cargar las aprobaciones",
          );
        }
      } else {
        setApprovals([]);
      }
      if (perms.view_costs) {
        try {
          setCosts(await api<CostSummary>("/costs", token));
          setCostsError("");
        } catch (err) {
          setCosts(null);
          setCostsError(
            err instanceof Error
              ? err.message
              : "No se pudieron cargar los costes",
          );
        }
      } else {
        setCosts(null);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudieron cargar los datos",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function onLogin(
    nextToken: string,
    nextUsername: string,
    nextRole: string,
    nextMustChange: boolean,
  ) {
    sessionStorage.setItem("agent_token", nextToken);
    sessionStorage.setItem("agent_user", nextUsername);
    sessionStorage.setItem("agent_role", nextRole);
    sessionStorage.setItem("agent_must_change", String(nextMustChange));
    setToken(nextToken);
    setUsername(nextUsername);
    setRole(nextRole);
    setMustChangePassword(nextMustChange);
  }

  async function logout() {
    if (token) {
      try {
        await api("/auth/logout", token, { method: "POST" });
      } catch {
        // La sesión local debe cerrarse aunque el servidor no responda.
      }
    }
    sessionStorage.clear();
    setToken("");
    setUsername("");
    setRole("");
    setMustChangePassword(false);
  }

  function passwordChanged() {
    sessionStorage.clear();
    setToken("");
    setUsername("");
    setRole("");
    setMustChangePassword(false);
  }

  async function decide(id: string, decision: "approve" | "reject") {
    try {
      await api(`/approvals/${id}/${decision}`, token, {
        method: "POST",
        body: JSON.stringify(
          decision === "reject"
            ? { rejection_reason: "Rechazada desde el panel" }
            : {},
        ),
      });
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudo registrar la decisión",
      );
    }
  }

  const integrationRows = useMemo(
    () => Object.entries(dashboard?.integrations ?? {}),
    [dashboard],
  );

  if (!token) return <Login onLogin={onLogin} />;
  if (mustChangePassword)
    return (
      <ChangePassword
        token={token}
        onComplete={passwordChanged}
        onLogout={() => void logout()}
      />
    );

  const navItems: Array<{ id: SectionId; label: string; icon: ReactNode }> = [
    {
      id: "resumen",
      label: translations.nav.resumen,
      icon: <Gauge size={18} />,
    },
    ...(permissions.approve
      ? [
          {
            id: "aprobaciones" as SectionId,
            label: translations.nav.aprobaciones,
            icon: <ShieldCheck size={18} />,
          },
        ]
      : []),
    {
      id: "catalogo",
      label: translations.nav.catalogo,
      icon: <Package size={18} />,
    },
    {
      id: "documentos",
      label: translations.nav.documentos,
      icon: <FileText size={18} />,
    },
    { id: "agentes", label: translations.nav.agentes, icon: <Bot size={18} /> },
    ...(permissions.manage_leads
      ? [
          {
            id: "clientes" as SectionId,
            label: translations.nav.clientes,
            icon: <Users size={18} />,
          },
        ]
      : []),
    {
      id: "automatizaciones",
      label: translations.nav.automatizaciones,
      icon: <Workflow size={18} />,
    },
    ...(permissions.manage_users
      ? [
          {
            id: "usuarios" as SectionId,
            label: translations.nav.usuarios,
            icon: <ShieldCheck size={18} />,
          },
        ]
      : []),
  ];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark small">AI</div>
          <div>
            <strong>Agentes IA</strong>
            <span>Control empresarial</span>
          </div>
        </div>
        <nav aria-label="Navegación principal">
          {navItems.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              className={section === item.id ? "active" : ""}
              aria-current={section === item.id ? "page" : undefined}
              onClick={(event) => {
                event.preventDefault();
                setSection(item.id);
              }}
            >
              {item.icon}
              {item.label}
            </a>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span>{username}</span>
          <button onClick={() => void logout()} aria-label="Cerrar sesión">
            <LogOut size={17} />
          </button>
        </div>
      </aside>

      <main className="content">
        <header className="topbar">
          <div>
            <p>Instalación</p>
            <h1>Resumen operativo</h1>
          </div>
          <div className="topbar-actions">
            <button
              className="icon-button"
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
              aria-label="Cambiar tema"
            >
              {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
            </button>
            <button
              className="secondary-button"
              onClick={() => void load()}
              disabled={loading}
            >
              <RefreshCw size={16} className={loading ? "spin" : ""} />
              Actualizar
            </button>
          </div>
        </header>

        {dashboard?.pilot_mode && (
          <div className="pilot-banner">
            <ShieldCheck size={18} />
            Modo piloto activo: las acciones sensibles requieren aprobación
            humana.
          </div>
        )}
        {error && (
          <div className="alert error" role="alert">
            <AlertTriangle size={18} />
            {error}
          </div>
        )}

        <div hidden={section !== "resumen"}>
          <section
            id="resumen"
            className="metrics-grid"
            aria-label="Indicadores principales"
          >
            <article className="metric">
              <span>Productos</span>
              <strong>{dashboard?.counts.products ?? "—"}</strong>
              <Package size={20} />
            </article>
            <article className="metric">
              <span>Clientes</span>
              <strong>{dashboard?.counts.customers ?? "—"}</strong>
              <Users size={20} />
            </article>
            <article className="metric">
              <span>Pedidos</span>
              <strong>{dashboard?.counts.orders ?? "—"}</strong>
              <Boxes size={20} />
            </article>
            <article className="metric">
              <span>Aprobaciones pendientes</span>
              <strong>{dashboard?.counts.pending_approvals ?? "—"}</strong>
              <ShieldCheck size={20} />
            </article>
          </section>

          <section className="panel-grid">
            <article className="panel">
              <div className="panel-heading">
                <div>
                  <p>Estado técnico</p>
                  <h2>Integraciones</h2>
                </div>
                <Activity size={21} />
              </div>
              <div className="integration-list">
                {integrationRows.length === 0 && (
                  <div className="empty-state">
                    No hay información disponible.
                  </div>
                )}
                {integrationRows.map(([name, state]) => (
                  <div className="integration-row" key={name}>
                    <span>
                      {name === "prestashop"
                        ? "PrestaShop"
                        : name === "ghl"
                          ? "GHL"
                          : name === "chatwoot"
                            ? "Chatwoot"
                            : "Activepieces"}
                    </span>
                    <span
                      className={`status ${state === "configured" ? "ok" : "warning"}`}
                    >
                      <CheckCircle2 size={14} />
                      {state === "configured"
                        ? "Configurado"
                        : "Pendiente de configuración"}
                    </span>
                  </div>
                ))}
              </div>
            </article>

            <article className="panel">
              <div className="panel-heading">
                <div>
                  <p>Uso de inteligencia artificial</p>
                  <h2>Consumo y costes</h2>
                </div>
                <Activity size={21} />
              </div>
              {!permissions.view_costs ? (
                <div className="empty-state">
                  Esta sección requiere rol administrador.
                </div>
              ) : costsError ? (
                <div className="alert error" role="alert">
                  {costsError}
                </div>
              ) : (
                <dl className="cost-list">
                  <div>
                    <dt>Ejecuciones</dt>
                    <dd>{costs?.total_executions ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Tokens</dt>
                    <dd>
                      {costs?.total_tokens_consumed?.toLocaleString("es-ES") ??
                        "—"}
                    </dd>
                  </div>
                  <div>
                    <dt>Coste estimado</dt>
                    <dd>
                      {costs
                        ? `${costs.total_estimated_cost_usd.toFixed(4)} USD`
                        : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt>Ejecuciones simuladas</dt>
                    <dd>{costs?.simulated_executions ?? "—"}</dd>
                  </div>
                </dl>
              )}
            </article>
          </section>
        </div>

        {permissions.approve && (
          <div hidden={section !== "aprobaciones"}>
            <section id="aprobaciones" className="panel approvals-panel">
              <div className="panel-heading">
                <div>
                  <p>Control humano</p>
                  <h2>Aprobaciones pendientes</h2>
                </div>
                <span className="counter">{approvals.length}</span>
              </div>
              {approvalsError ? (
                <div className="alert error" role="alert">
                  {approvalsError}
                </div>
              ) : approvals.length === 0 ? (
                <div className="empty-state">
                  <CheckCircle2 size={24} />
                  No hay acciones pendientes de revisión.
                </div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Acción</th>
                        <th>Referencia</th>
                        <th>Fecha</th>
                        <th>Estado</th>
                        <th>Decisión</th>
                      </tr>
                    </thead>
                    <tbody>
                      {approvals.map((approval) => (
                        <tr key={approval.id}>
                          <td>
                            {approval.action_type === "issue_invoice"
                              ? "Aprobar borrador de factura"
                              : approval.action_type}
                          </td>
                          <td>{approval.target_key}</td>
                          <td>
                            {new Date(approval.created_at).toLocaleString(
                              "es-ES",
                            )}
                          </td>
                          <td>
                            <span className="status warning">Pendiente</span>
                          </td>
                          <td className="actions">
                            <button
                              className="success-button"
                              onClick={() =>
                                void decide(approval.id, "approve")
                              }
                            >
                              Aprobar
                            </button>
                            <button
                              className="danger-button"
                              onClick={() => void decide(approval.id, "reject")}
                            >
                              Rechazar
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )}

        <div hidden={section !== "catalogo"}>
          <ProductsSection
            token={token}
            canImport={permissions.import_catalog}
          />
        </div>
        <div hidden={section !== "documentos"}>
          <DocumentsSection token={token} />
        </div>
        <div hidden={section !== "agentes"}>
          <AgentsSection token={token} />
        </div>
        {permissions.manage_leads && (
          <div hidden={section !== "clientes"}>
            <LeadsSection token={token} />
          </div>
        )}
        <div hidden={section !== "automatizaciones"}>
          <AutomationsSection dashboard={dashboard} />
        </div>
        {permissions.manage_users && (
          <div hidden={section !== "usuarios"}>
            <UsersSection token={token} />
          </div>
        )}
      </main>
    </div>
  );
}
