import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  Boxes,
  CheckCircle2,
  Clock,
  FileText,
  Gauge,
  LogOut,
  MessageSquare,
  Package,
  RefreshCw,
  ShieldCheck,
  Mail,
  Users,
  Webhook,
  Workflow,
} from "lucide-react";
import { apiRequest, AUTH_EXPIRED_EVENT } from "./api";
import { api } from "./apiHelpers";
import {
  approvalActionLabel,
  approvalFieldLabel,
  approvalFieldValue,
  clearStoredSession,
  formatDate,
  formatNumber,
  integrationLabel,
  integrationStatus,
  roleLabel,
  sectionFromHash,
  syncStatusClass,
  syncStatusLabel,
} from "./appFormat";
import {
  ADMIN_ROLES,
  ADVANCED_SECTIONS,
  DEFAULT_ACCENT,
  NAV_GROUP_LABELS,
  NAV_GROUP_ORDER,
  OPERATOR_ROLES,
  SECTION_TITLES,
  type Approval,
  type ApprovalIntent,
  type CostSummary,
  type Dashboard,
  type NavGroupId,
  type SectionId,
  type SyncHistoryRow,
} from "./appTypes";
import { translations } from "./i18n/es";
import { CeoChat, type CeoChatHandle } from "./ceoChat";
import {
  completeOnboarding,
  getOnboardingMode,
  OnboardingOverlay,
  type OnboardingMode,
} from "./onboarding";
import { EmailSection } from "./email";
import { WebhooksSection } from "./webhooks";
import {
  AgentRegistrySection,
  CommerceSection,
  ContentGrowthSection,
  SchedulerSection,
} from "./productionModules";
import { ChangePassword, Login } from "./sections/Login";
import { ProductsSection } from "./sections/Products";
import { ClientesSection } from "./sections/Clients";
import { DocumentsSection } from "./sections/Documents";
import { UsersSection } from "./sections/Users";
import { AutomationsSection } from "./sections/Automations";
import { TodaySection } from "./today";

export default function App() {
  const [token, setToken] = useState(
    () => sessionStorage.getItem("agent_token") ?? "",
  );
  const [username, setUsername] = useState(
    () => sessionStorage.getItem("agent_user") ?? "",
  );
  const [mustChangePassword, setMustChangePassword] = useState(
    () => sessionStorage.getItem("agent_must_change") === "true",
  );
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [costs, setCosts] = useState<CostSummary | null>(null);
  const [syncHistory, setSyncHistory] = useState<SyncHistoryRow[] | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [approvalsError, setApprovalsError] = useState("");
  const [costsError, setCostsError] = useState("");
  const [syncHistoryError, setSyncHistoryError] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [loginNotice, setLoginNotice] = useState("");
  const [section, setSection] = useState<SectionId>(sectionFromHash);
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [decisionIntent, setDecisionIntent] = useState<ApprovalIntent | null>(
    null,
  );
  const [decisionConfirmation, setDecisionConfirmation] = useState("");
  const [rejectionReason, setRejectionReason] = useState("");
  const [decisionError, setDecisionError] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [runningAgents, setRunningAgents] = useState(false);
  const [agentsNotice, setAgentsNotice] = useState("");
  const decisionInputRef = useRef<HTMLInputElement>(null);
  const loadRevisionRef = useRef(0);
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("theme") as "light" | "dark") ?? "light",
  );
  const [accent, setAccent] = useState<string>(
    () => localStorage.getItem("accent") ?? DEFAULT_ACCENT,
  );
  const [density, setDensity] = useState<"comfortable" | "compact">(
    () =>
      (localStorage.getItem("density") as "comfortable" | "compact") ??
      "comfortable",
  );
  const [guidedMode, setGuidedMode] = useState<OnboardingMode>(() =>
    getOnboardingMode(),
  );
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  // Modo simple por defecto: oculta las secciones técnicas hasta que el
  // usuario las pida. La preferencia se persiste por navegador/instalación.
  const [advancedMode, setAdvancedMode] = useState<boolean>(
    () => localStorage.getItem("advanced-mode") === "on",
  );
  const chatRef = useRef<CeoChatHandle | null>(null);

  useEffect(() => {
    localStorage.setItem("advanced-mode", advancedMode ? "on" : "off");
  }, [advancedMode]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.dataset.density = density;
    localStorage.setItem("density", density);
  }, [density]);

  useEffect(() => {
    const style = document.documentElement.style;
    style.setProperty("--accent", accent);
    style.setProperty(
      "--accent-soft",
      `color-mix(in srgb, ${accent} 12%, transparent)`,
    );
  }, [accent]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api<{ accent_color?: string }>("/appearance/settings", token)
      .then((data) => {
        if (cancelled || !data?.accent_color) return;
        if (!/^#[0-9a-fA-F]{6}$/.test(data.accent_color)) return;
        setAccent(data.accent_color);
        localStorage.setItem("accent", data.accent_color);
      })
      .catch(() => {
        // Sin conexión o instalación antigua: se mantiene el acento local.
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    const expireSession = () => {
      loadRevisionRef.current += 1;
      clearStoredSession();
      setToken("");
      setUsername("");
      setMustChangePassword(false);
      setDashboard(null);
      setApprovals([]);
      setCosts(null);
      setSyncHistory(null);
      setDecisionIntent(null);
      setLoginNotice(
        "Tu sesión ha caducado o ha sido revocada. Vuelve a identificarte.",
      );
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, expireSession);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expireSession);
  }, []);

  useEffect(() => {
    // Onboarding: al confirmar la sesión (dashboard cargado) y sin
    // preferencia guardada, se abre el asistente guiado de primeros pasos.
    if (dashboard && guidedMode === "active") {
      setOnboardingOpen(true);
    }
  }, [dashboard, guidedMode]);

  useEffect(() => {
    if (!decisionIntent) return;
    decisionInputRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !deciding) setDecisionIntent(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [deciding, decisionIntent]);

  // RBAC: el backend es la única autoridad. Hasta que /dashboard responda,
  // todas las acciones sensibles permanecen cerradas (fail-closed).
  const permissions = dashboard?.permissions ?? {
    approve: false,
    manage_leads: false,
    manage_users: false,
    view_costs: false,
    import_catalog: false,
  };
  // Las capacidades de módulos nuevos se derivan del rol confirmado por
  // /dashboard. Las decisiones de aprobación siguen limitadas a ADMIN_ROLES.
  const isAdmin = ADMIN_ROLES.has(dashboard?.role ?? "");
  const canOperateBusiness = OPERATOR_ROLES.has(dashboard?.role ?? "");
  const canDecideApprovals = isAdmin;

  useEffect(() => {
    const syncSectionWithHash = () => {
      const candidate = sectionFromHash();
      if (!dashboard) {
        setSection("asistente");
        return;
      }
      const allowedByRole =
        candidate === "asistente" ||
        candidate === "resumen" ||
        candidate === "catalogo" ||
        candidate === "documentos" ||
        candidate === "agentes" ||
        candidate === "automatizaciones" ||
        (candidate === "aprobaciones" && permissions.approve) ||
        (candidate === "clientes" && permissions.manage_leads) ||
        (candidate === "ventas" && canOperateBusiness) ||
        (candidate === "contenido" && canOperateBusiness) ||
        (candidate === "tareas" && isAdmin) ||
        (candidate === "webhooks" && isAdmin) ||
        (candidate === "email" && isAdmin) ||
        (candidate === "usuarios" && permissions.manage_users);
      // En modo simple las secciones técnicas no son alcanzables ni por hash.
      const allowed =
        allowedByRole && (advancedMode || !ADVANCED_SECTIONS.has(candidate));
      if (allowed) {
        setSection(candidate);
      } else {
        setSection("asistente");
        window.history.replaceState(null, "", "#asistente");
      }
    };
    syncSectionWithHash();
    window.addEventListener("hashchange", syncSectionWithHash);
    return () => window.removeEventListener("hashchange", syncSectionWithHash);
  }, [
    dashboard,
    advancedMode,
    canOperateBusiness,
    isAdmin,
    permissions.approve,
    permissions.manage_leads,
    permissions.manage_users,
  ]);

  useEffect(() => {
    document.title = `${SECTION_TITLES[section]} · Plataforma de agentes IA`;
  }, [section]);

  // Carga parcial por rol: cada bloque es independiente y un 403 nunca
  // tumba el resto del panel (antes Promise.all hacía fallar todo el load).
  async function load() {
    const revision = ++loadRevisionRef.current;
    const requestToken = token;
    const isCurrent = () => revision === loadRevisionRef.current;
    if (!requestToken) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const dashboardData = await api<Dashboard>("/dashboard", requestToken);
      if (!isCurrent()) return;
      setDashboard(dashboardData);
      sessionStorage.setItem("agent_role", dashboardData.role);
      const perms = dashboardData.permissions;
      if (perms.approve) {
        try {
          const nextApprovals = await api<Approval[]>(
            "/approvals?status_filter=pending",
            requestToken,
          );
          if (!isCurrent()) return;
          setApprovals(nextApprovals);
          setApprovalsError("");
        } catch (err) {
          if (!isCurrent()) return;
          setApprovals([]);
          setApprovalsError(
            err instanceof Error
              ? err.message
              : "No se pudieron cargar las aprobaciones",
          );
        }
      } else {
        setApprovals([]);
        setApprovalsError("");
      }
      if (perms.view_costs) {
        try {
          const nextCosts = await api<CostSummary>("/costs", requestToken);
          if (!isCurrent()) return;
          setCosts(nextCosts);
          setCostsError("");
        } catch (err) {
          if (!isCurrent()) return;
          setCosts(null);
          setCostsError(
            err instanceof Error
              ? err.message
              : "No se pudieron cargar los costes",
          );
        }
      } else {
        setCosts(null);
        setCostsError("");
      }
      try {
        const history = await api<{ history: SyncHistoryRow[] }>(
          "/integrations/prestashop/sync/history?limit=8",
          requestToken,
        );
        if (!isCurrent()) return;
        setSyncHistory(history.history ?? []);
        setSyncHistoryError("");
      } catch (err) {
        if (!isCurrent()) return;
        setSyncHistory(null);
        setSyncHistoryError(
          err instanceof Error
            ? err.message
            : "No se pudo cargar el historial de sincronización",
        );
      }
    } catch (err) {
      if (!isCurrent()) return;
      setDashboard(null);
      setApprovals([]);
      setCosts(null);
      setSyncHistory(null);
      setError(
        err instanceof Error ? err.message : "No se pudieron cargar los datos",
      );
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function refreshAll() {
    setRefreshRevision((value) => value + 1);
    void load();
  }

  function toggleAdvancedMode() {
    const next = !advancedMode;
    setAdvancedMode(next);
    if (!next && ADVANCED_SECTIONS.has(section)) {
      setSection("asistente");
      window.history.replaceState(null, "", "#asistente");
    }
  }

  function onLogin(
    nextToken: string,
    nextUsername: string,
    nextRole: string,
    nextMustChange: boolean,
  ) {
    loadRevisionRef.current += 1;
    setLoginNotice("");
    sessionStorage.setItem("agent_token", nextToken);
    sessionStorage.setItem("agent_user", nextUsername);
    sessionStorage.setItem("agent_role", nextRole);
    sessionStorage.setItem("agent_must_change", String(nextMustChange));
    setToken(nextToken);
    setUsername(nextUsername);
    setMustChangePassword(nextMustChange);
  }

  async function logout() {
    const logoutToken = token;
    loadRevisionRef.current += 1;
    clearStoredSession();
    setToken("");
    setUsername("");
    setMustChangePassword(false);
    setDashboard(null);
    setApprovals([]);
    setCosts(null);
    setSyncHistory(null);
    setDecisionIntent(null);
    setSection("resumen");
    window.history.replaceState(null, "", "#resumen");
    if (logoutToken) {
      try {
        await apiRequest("/auth/logout", {
          token: logoutToken,
          method: "POST",
          expireSessionOnUnauthorized: false,
        });
      } catch {
        // La sesión local ya está cerrada aunque el servidor no responda.
      }
    }
  }

  function passwordChanged() {
    loadRevisionRef.current += 1;
    clearStoredSession();
    setToken("");
    setUsername("");
    setMustChangePassword(false);
    setLoginNotice("Contraseña actualizada. Inicia sesión de nuevo.");
  }

  function openDecision(approval: Approval, decision: "approve" | "reject") {
    setDecisionIntent({ approval, decision });
    setDecisionConfirmation("");
    setRejectionReason("");
    setDecisionError("");
  }

  function closeDecision() {
    if (deciding) return;
    setDecisionIntent(null);
    setDecisionConfirmation("");
    setRejectionReason("");
    setDecisionError("");
  }

  async function runAgentProposals() {
    if (!canDecideApprovals || runningAgents) return;
    setRunningAgents(true);
    setAgentsNotice("");
    setApprovalsError("");
    try {
      const result = await api<{
        proposed: number;
        by_agent: Record<string, number>;
      }>("/agent-proposals/run", token, { method: "POST" });
      const parts = Object.entries(result.by_agent)
        .filter(([, count]) => count > 0)
        .map(([agent, count]) => `${count} de ${agent}`);
      setAgentsNotice(
        result.proposed > 0
          ? `Propuestas creadas: ${parts.join(", ")}. Revisa y decide en este panel.`
          : "Sin propuestas nuevas: los agentes ya habían propuesto o no hay señales pendientes.",
      );
      const nextApprovals = await api<Approval[]>(
        "/approvals?status_filter=pending",
        token,
      );
      setApprovals(nextApprovals);
    } catch (err) {
      setApprovalsError(
        err instanceof Error
          ? err.message
          : "No se pudo ejecutar la ronda de agentes",
      );
    } finally {
      setRunningAgents(false);
    }
  }

  async function decide() {
    if (!decisionIntent || !canDecideApprovals) return;
    const { approval, decision } = decisionIntent;
    if (decisionConfirmation.trim() !== approval.target_key) {
      setDecisionError("La referencia escrita no coincide exactamente.");
      return;
    }
    if (decision === "reject" && rejectionReason.trim().length < 5) {
      setDecisionError("Indica un motivo de rechazo de al menos 5 caracteres.");
      return;
    }
    setDeciding(true);
    setDecisionError("");
    try {
      await api(`/approvals/${approval.id}/${decision}`, token, {
        method: "POST",
        body: JSON.stringify(
          decision === "reject"
            ? { rejection_reason: rejectionReason.trim() }
            : {},
        ),
      });
      setDecisionIntent(null);
      setDecisionConfirmation("");
      setRejectionReason("");
      await load();
    } catch (err) {
      setDecisionError(
        err instanceof Error ? err.message : "No se pudo registrar la decisión",
      );
    } finally {
      setDeciding(false);
    }
  }

  const integrationRows = useMemo(
    () => Object.entries(dashboard?.integrations ?? {}),
    [dashboard],
  );

  if (!token) return <Login onLogin={onLogin} notice={loginNotice} />;
  if (mustChangePassword)
    return (
      <ChangePassword
        token={token}
        onComplete={passwordChanged}
        onLogout={() => void logout()}
      />
    );

  const navItems: Array<{
    id: SectionId;
    label: string;
    icon: ReactNode;
    group: NavGroupId;
  }> = [
    // Inicio: la operación diaria en un solo lugar.
    {
      id: "asistente",
      label: "Asistente",
      icon: <MessageSquare size={18} />,
      group: "inicio" as NavGroupId,
    },
    {
      id: "resumen",
      label: "Hoy",
      icon: <Gauge size={18} />,
      group: "inicio" as NavGroupId,
    },
    ...(permissions.approve
      ? [
          {
            id: "aprobaciones" as SectionId,
            label: translations.nav.aprobaciones,
            icon: <ShieldCheck size={18} />,
            group: "inicio" as NavGroupId,
          },
        ]
      : []),
    // Ventas: el ciclo comercial (CRM + facturación).
    ...(permissions.manage_leads
      ? [
          {
            id: "clientes" as SectionId,
            label: translations.nav.clientes,
            icon: <Users size={18} />,
            group: "ventas" as NavGroupId,
          },
        ]
      : []),
    ...(canOperateBusiness
      ? [
          {
            id: "ventas" as SectionId,
            label: "Ventas y facturación",
            icon: <Boxes size={18} />,
            group: "ventas" as NavGroupId,
          },
        ]
      : []),
    // Catálogo: lo que la empresa ofrece y la base de conocimiento del
    // asistente (RAG).
    {
      id: "catalogo",
      label: translations.nav.catalogo,
      icon: <Package size={18} />,
      group: "catalogo" as NavGroupId,
    },
    {
      id: "documentos",
      label: translations.nav.documentos,
      icon: <FileText size={18} />,
      group: "catalogo" as NavGroupId,
    },
    // Marketing: contenido, SEO y reglas automáticas de captación/seguimiento.
    ...(canOperateBusiness
      ? [
          {
            id: "contenido" as SectionId,
            label: "Contenido y SEO",
            icon: <FileText size={18} />,
            group: "marketing" as NavGroupId,
          },
        ]
      : []),
    {
      id: "automatizaciones",
      label: translations.nav.automatizaciones,
      icon: <Workflow size={18} />,
      group: "marketing" as NavGroupId,
    },
    // Ajustes: configuración y módulos técnicos (visibles según rol).
    {
      id: "agentes",
      label: translations.nav.agentes,
      icon: <Bot size={18} />,
      group: "ajustes" as NavGroupId,
    },
    ...(isAdmin
      ? [
          {
            id: "tareas" as SectionId,
            label: "Tareas programadas",
            icon: <Clock size={18} />,
            group: "ajustes" as NavGroupId,
          },
          {
            id: "webhooks" as SectionId,
            label: "Webhooks salientes",
            icon: <Webhook size={18} />,
            group: "ajustes" as NavGroupId,
          },
          {
            id: "email" as SectionId,
            label: "Email integrado",
            icon: <Mail size={18} />,
            group: "ajustes" as NavGroupId,
          },
        ]
      : []),
    ...(permissions.manage_users
      ? [
          {
            id: "usuarios" as SectionId,
            label: translations.nav.usuarios,
            icon: <ShieldCheck size={18} />,
            group: "ajustes" as NavGroupId,
          },
        ]
      : []),
  ];
  // Modo guiado (T-072): mientras el onboarding no esté completado, la barra
  // lateral solo muestra Asistente y Resumen. El resto aparece al terminar
  // (o pulsando «Mostrar todos los módulos»).
  const visibleNavItems =
    guidedMode === "active"
      ? navItems.filter(
          (item) => item.id === "asistente" || item.id === "resumen",
        )
      : advancedMode
        ? navItems
        : navItems.filter((item) => !ADVANCED_SECTIONS.has(item.id));

  // Menú agrupado por intención: los grupos sin secciones permitidas por el
  // rol no se renderizan (p. ej. un viewer no ve «Ventas»).
  const navGroups = NAV_GROUP_ORDER.map((groupId) => ({
    id: groupId,
    label: NAV_GROUP_LABELS[groupId],
    items: visibleNavItems.filter((item) => item.group === groupId),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#contenido-principal">
        Saltar al contenido principal
      </a>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark small">AI</div>
          <div>
            <strong>Agentes IA</strong>
            <span>Control empresarial</span>
          </div>
        </div>
        <nav aria-label="Navegación principal">
          {navGroups.map((group) => (
            <div className="nav-group" key={group.id}>
              <p className="nav-group-label">{group.label}</p>
              {group.items.map((item) => (
                <a
                  key={item.id}
                  href={`#${item.id}`}
                  className={section === item.id ? "active" : ""}
                  aria-current={section === item.id ? "page" : undefined}
                  onClick={() => setSection(item.id)}
                >
                  {item.icon}
                  {item.label}
                </a>
              ))}
            </div>
          ))}
        </nav>
        {guidedMode === "active" && (
          <button
            type="button"
            className="sidebar-guided-exit"
            onClick={() => {
              completeOnboarding();
              setGuidedMode("done");
              setOnboardingOpen(false);
            }}
          >
            Mostrar todos los módulos
          </button>
        )}
        {guidedMode !== "active" && (
          <button
            type="button"
            className="sidebar-mode-toggle"
            aria-pressed={advancedMode}
            aria-label={
              advancedMode ? "Activar modo simple" : "Activar modo avanzado"
            }
            onClick={toggleAdvancedMode}
          >
            {advancedMode ? "Modo simple" : "Modo avanzado"}
          </button>
        )}
        <div className="sidebar-footer">
          <span>
            {username}
            <small>
              {dashboard?.role
                ? roleLabel(dashboard.role)
                : "Verificando permisos…"}
            </small>
          </span>
          <button
            type="button"
            onClick={() => void logout()}
            aria-label="Cerrar sesión"
          >
            <LogOut size={17} />
          </button>
        </div>
      </aside>

      <main
        id="contenido-principal"
        className="content"
        tabIndex={-1}
        aria-busy={loading}
      >
        <header className="topbar">
          <div>
            <p>Instalación</p>
            <h1>{SECTION_TITLES[section]}</h1>
            {dashboard && (
              <span className="installation-meta">
                {dashboard.installation_id} · v{dashboard.installed_version}
              </span>
            )}
          </div>
          <div className="topbar-actions">
            <div className="segmented" role="group" aria-label="Tema">
              <button
                className="segmented-item"
                onClick={() => setTheme("light")}
                aria-label="Activar tema claro"
                aria-pressed={theme === "light"}
              >
                Claro
              </button>
              <button
                className="segmented-item"
                onClick={() => setTheme("dark")}
                aria-label="Activar tema oscuro"
                aria-pressed={theme === "dark"}
              >
                Oscuro
              </button>
            </div>
            <div className="segmented" role="group" aria-label="Densidad">
              <button
                className="segmented-item"
                onClick={() => setDensity("comfortable")}
                aria-label="Activar modo cómodo"
                aria-pressed={density === "comfortable"}
              >
                Cómodo
              </button>
              <button
                className="segmented-item"
                onClick={() => setDensity("compact")}
                aria-label="Activar modo compacto"
                aria-pressed={density === "compact"}
              >
                Compacto
              </button>
            </div>
            <button
              className="secondary-button"
              onClick={refreshAll}
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

        <div hidden={section !== "asistente"}>
          <section id="asistente" className="panel asistente-panel">
            <div className="panel-heading">
              <div>
                <p>Tu empresa en una conversación</p>
                <h2>Asistente</h2>
              </div>
              <span className="badge badge-green">Moneda: EUR</span>
            </div>
            <p className="muted">
              Pregunta en lenguaje natural y el asistente consulta los datos
              reales de todos los módulos (ventas, pipeline, leads, actividades,
              aprobaciones, bandeja social, stock, agentes y automatizaciones).
              Las acciones — follow-ups, pausar o activar automatizaciones —
              quedan como propuestas que solo tienes que confirmar. Todo en
              euros (EUR).
            </p>
            <CeoChat ref={chatRef} token={token} />
          </section>
        </div>
        <div hidden={section !== "resumen"}>
          <TodaySection token={token} permissions={permissions} />
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
              <span>Presupuestos</span>
              <strong>{dashboard?.counts.quotes ?? "—"}</strong>
              <FileText size={20} />
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
                {integrationRows.map(([name, state]) => {
                  const status = integrationStatus(state);
                  return (
                    <div className="integration-row" key={name}>
                      <span>{integrationLabel(name)}</span>
                      <span className={`status ${status.className}`}>
                        <CheckCircle2 size={14} />
                        {status.label}
                      </span>
                    </div>
                  );
                })}
              </div>

              <div className="sync-history">
                <div className="sync-history-title">
                  <Clock size={14} />
                  Historial de sincronización
                </div>
                {syncHistoryError ? (
                  <div className="empty-state compact">{syncHistoryError}</div>
                ) : syncHistory === null ? (
                  <div className="empty-state compact">Cargando…</div>
                ) : syncHistory.length === 0 ? (
                  <div className="empty-state compact">
                    Todavía no hay ejecuciones registradas.
                  </div>
                ) : (
                  syncHistory.map((row) => (
                    <div className="integration-row" key={row.id}>
                      <span>
                        {formatDate(row.started_at, false)}
                        <small>
                          {" "}
                          · {row.incremental
                            ? "incremental"
                            : "completo"} ·{" "}
                          {row.duration_seconds == null
                            ? "—"
                            : formatNumber(row.duration_seconds, 0)}{" "}
                          s
                          {row.total_remote > 0
                            ? ` · ${row.total_remote} productos`
                            : ""}
                        </small>
                        {row.error && (
                          <small className="sync-error">{row.error}</small>
                        )}
                      </span>
                      <span className={`status ${syncStatusClass(row.status)}`}>
                        {syncStatusLabel(row.status)}
                      </span>
                    </div>
                  ))
                )}
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
              ) : costs === null ? (
                <div className="empty-state" role="status">
                  Cargando consumo y costes…
                </div>
              ) : (
                <>
                  {costs.simulated_executions > 0 && (
                    <div className="alert error" role="alert">
                      Se han registrado {costs.simulated_executions} ejecuciones
                      simuladas. Revisa la configuración antes de usar este
                      entorno como producción.
                    </div>
                  )}
                  <dl className="cost-list">
                    <div>
                      <dt>Ejecuciones</dt>
                      <dd>{costs.total_executions}</dd>
                    </div>
                    <div>
                      <dt>Tokens</dt>
                      <dd>
                        {costs.total_tokens_consumed.toLocaleString("es-ES")}
                      </dd>
                    </div>
                    <div>
                      <dt>Coste estimado</dt>
                      <dd>
                        {formatNumber(costs.total_estimated_cost_usd, 4)} USD
                      </dd>
                    </div>
                    <div>
                      <dt>Latencia media</dt>
                      <dd>{formatNumber(costs.avg_latency_ms, 0)} ms</dd>
                    </div>
                    <div>
                      <dt>Ejecuciones simuladas</dt>
                      <dd>{costs.simulated_executions}</dd>
                    </div>
                  </dl>
                </>
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
                {canDecideApprovals && (
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={runningAgents}
                    onClick={runAgentProposals}
                  >
                    {runningAgents ? "Ejecutando…" : "Ejecutar agentes"}
                  </button>
                )}
              </div>
              {agentsNotice && (
                <div className="notice-box" role="status">
                  {agentsNotice}
                </div>
              )}
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
                    <caption className="sr-only">
                      Solicitudes de aprobación pendientes
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Acción</th>
                        <th scope="col">Objetivo</th>
                        <th scope="col">Datos a revisar</th>
                        <th scope="col">Fecha</th>
                        <th scope="col">Estado</th>
                        <th scope="col">Decisión</th>
                      </tr>
                    </thead>
                    <tbody>
                      {approvals.map((approval) => (
                        <tr key={approval.id}>
                          <td>
                            {approval.action_label ??
                              approvalActionLabel(approval.action_type)}
                          </td>
                          <td>
                            <span className="approval-target">
                              {approval.target_label ?? approval.target_key}
                            </span>
                            {approval.target_label &&
                              approval.target_label !== approval.target_key && (
                                <small className="muted-text">
                                  {approval.target_key}
                                </small>
                              )}
                          </td>
                          <td>
                            {Object.keys(approval.payload).length === 0 ? (
                              "Sin detalle adicional"
                            ) : (
                              <details>
                                <summary>Ver detalle</summary>
                                <dl className="approval-details">
                                  {Object.entries(approval.payload).map(
                                    ([field, value]) => (
                                      <div key={field}>
                                        <dt>{approvalFieldLabel(field)}</dt>
                                        <dd>
                                          {approvalFieldValue(field, value)}
                                        </dd>
                                      </div>
                                    ),
                                  )}
                                </dl>
                              </details>
                            )}
                          </td>
                          <td>{formatDate(approval.created_at)}</td>
                          <td>
                            <span className="status warning">Pendiente</span>
                          </td>
                          <td>
                            {canDecideApprovals ? (
                              <div className="actions">
                                <button
                                  type="button"
                                  className="success-button"
                                  onClick={() =>
                                    openDecision(approval, "approve")
                                  }
                                  aria-label={`Aprobar ${approval.target_label ?? approval.target_key}`}
                                >
                                  Aprobar
                                </button>
                                <button
                                  type="button"
                                  className="danger-button"
                                  onClick={() =>
                                    openDecision(approval, "reject")
                                  }
                                  aria-label={`Rechazar ${approval.target_label ?? approval.target_key}`}
                                >
                                  Rechazar
                                </button>
                              </div>
                            ) : (
                              <span className="muted-text">Solo lectura</span>
                            )}
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
            refreshRevision={refreshRevision}
            active={section === "catalogo"}
          />
        </div>
        {canOperateBusiness && (
          <div hidden={section !== "ventas"}>
            <CommerceSection
              token={token}
              canWrite={canOperateBusiness}
              refreshRevision={refreshRevision}
              active={section === "ventas"}
            />
          </div>
        )}
        <div hidden={section !== "documentos"}>
          <DocumentsSection token={token} refreshRevision={refreshRevision} />
        </div>
        <div hidden={section !== "agentes"}>
          <AgentRegistrySection
            token={token}
            canWrite={isAdmin}
            refreshRevision={refreshRevision}
          />
        </div>
        {permissions.manage_leads && (
          <div hidden={section !== "clientes"}>
            <ClientesSection
              token={token}
              isAdmin={isAdmin}
              refreshRevision={refreshRevision}
              active={section === "clientes"}
            />
          </div>
        )}
        {canOperateBusiness && (
          <div hidden={section !== "contenido"}>
            <ContentGrowthSection
              token={token}
              canWrite={isAdmin}
              refreshRevision={refreshRevision}
            />
          </div>
        )}
        {isAdmin && (
          <div hidden={section !== "tareas"}>
            <SchedulerSection
              token={token}
              canWrite={isAdmin}
              refreshRevision={refreshRevision}
            />
          </div>
        )}
        {isAdmin && (
          <div hidden={section !== "webhooks"}>
            <WebhooksSection token={token} refreshRevision={refreshRevision} />
          </div>
        )}
        {isAdmin && (
          <div hidden={section !== "email"}>
            <EmailSection token={token} refreshRevision={refreshRevision} />
          </div>
        )}
        <div hidden={section !== "automatizaciones"}>
          <AutomationsSection
            token={token}
            canWrite={isAdmin}
            refreshRevision={refreshRevision}
          />
        </div>
        {permissions.manage_users && (
          <div hidden={section !== "usuarios"}>
            <UsersSection
              token={token}
              refreshRevision={refreshRevision}
              accent={accent}
              onAccentChange={setAccent}
            />
          </div>
        )}

        {decisionIntent && (
          <div className="dialog-backdrop">
            <section
              className="confirmation-dialog"
              role="dialog"
              aria-modal="true"
              aria-labelledby="decision-title"
              aria-describedby="decision-description"
            >
              <div>
                <p>Acción sensible</p>
                <h2 id="decision-title">
                  {decisionIntent.decision === "approve"
                    ? "Confirmar aprobación"
                    : "Confirmar rechazo"}
                </h2>
              </div>
              <p id="decision-description">
                {decisionIntent.approval.action_label ??
                  approvalActionLabel(decisionIntent.approval.action_type)}{" "}
                sobre{" "}
                <strong>
                  {decisionIntent.approval.target_label ??
                    decisionIntent.approval.target_key}
                </strong>
                . Esta decisión quedará auditada y no debe tomarse sin revisar
                los datos de la solicitud.
              </p>
              {Object.keys(decisionIntent.approval.payload).length > 0 && (
                <dl className="approval-details dialog-details">
                  {Object.entries(decisionIntent.approval.payload).map(
                    ([field, value]) => (
                      <div key={field}>
                        <dt>{approvalFieldLabel(field)}</dt>
                        <dd>{approvalFieldValue(field, value)}</dd>
                      </div>
                    ),
                  )}
                </dl>
              )}
              <label>
                Escribe la referencia exacta para confirmar
                <input
                  ref={decisionInputRef}
                  value={decisionConfirmation}
                  onChange={(event) =>
                    setDecisionConfirmation(event.target.value)
                  }
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <small className="muted-text">
                Referencia a escribir:{" "}
                <code>{decisionIntent.approval.target_key}</code>
              </small>
              {decisionIntent.decision === "reject" && (
                <label>
                  Motivo del rechazo
                  <textarea
                    value={rejectionReason}
                    onChange={(event) => setRejectionReason(event.target.value)}
                    minLength={5}
                    maxLength={1_000}
                    rows={3}
                    required
                  />
                </label>
              )}
              {decisionError && (
                <div className="alert error" role="alert">
                  {decisionError}
                </div>
              )}
              <div className="dialog-actions">
                <button
                  type="button"
                  className={
                    decisionIntent.decision === "approve"
                      ? "success-button"
                      : "danger-button"
                  }
                  disabled={
                    deciding ||
                    decisionConfirmation.trim() !==
                      decisionIntent.approval.target_key ||
                    (decisionIntent.decision === "reject" &&
                      rejectionReason.trim().length < 5)
                  }
                  onClick={() => void decide()}
                >
                  {deciding
                    ? "Guardando…"
                    : decisionIntent.decision === "approve"
                      ? "Confirmar aprobación"
                      : "Confirmar rechazo"}
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={deciding}
                  onClick={closeDecision}
                >
                  Cancelar
                </button>
              </div>
            </section>
          </div>
        )}
      </main>

      {onboardingOpen && (
        <OnboardingOverlay
          onAskExample={(question) => chatRef.current?.send(question)}
          onFinish={() => {
            completeOnboarding();
            setGuidedMode("done");
            setOnboardingOpen(false);
          }}
          onContinueGuided={() => setOnboardingOpen(false)}
        />
      )}
    </div>
  );
}
