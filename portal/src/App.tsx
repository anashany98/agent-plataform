import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
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
} from 'lucide-react';
import { translations } from './i18n/es';

type Approval = {
  id: string;
  action_type: string;
  target_key: string;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
};

type Dashboard = {
  installation_id: string;
  installed_version: string;
  pilot_mode: boolean;
  integrations: Record<string, string>;
  counts: Record<string, number>;
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
  | 'resumen'
  | 'aprobaciones'
  | 'catalogo'
  | 'documentos'
  | 'agentes'
  | 'automatizaciones'
  | 'usuarios';

const API_BASE = '/api/bridge';

async function api<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : 'No se pudo completar la operación';
    throw new Error(detail);
  }
  return data as T;
}

function Login({ onLogin }: { onLogin: (token: string, username: string, mustChangePassword: boolean) => void }) {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? 'No se pudo iniciar sesión');
      onLogin(data.access_token, data.username, Boolean(data.must_change_password));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error inesperado');
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
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
          </label>
          <label>
            Contraseña
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </label>
          {error && <div className="alert error" role="alert">{error}</div>}
          <button className="primary-button" disabled={loading}>{loading ? 'Accediendo…' : 'Acceder'}</button>
        </form>
      </section>
    </main>
  );
}

function ChangePassword({ token, onComplete, onLogout }: { token: string; onComplete: () => void; onLogout: () => void }) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    if (newPassword !== confirmation) {
      setError('Las contraseñas nuevas no coinciden');
      return;
    }
    setLoading(true);
    try {
      await api('/auth/change-password', token, {
        method: 'POST',
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo cambiar la contraseña');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-card" aria-labelledby="password-title">
        <div className="brand-mark">AI</div>
        <h1 id="password-title">Cambia la contraseña temporal</h1>
        <p>Por seguridad, debes crear una contraseña personal antes de acceder al panel.</p>
        <form onSubmit={submit}>
          <label>Contraseña temporal<input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} autoComplete="current-password" required /></label>
          <label>Nueva contraseña<input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" minLength={12} required /></label>
          <label>Repite la nueva contraseña<input type="password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} autoComplete="new-password" minLength={12} required /></label>
          <p className="password-help">Mínimo 12 caracteres, con mayúscula, minúscula, número y símbolo.</p>
          {error && <div className="alert error" role="alert">{error}</div>}
          <button className="primary-button" disabled={loading}>{loading ? 'Guardando…' : 'Cambiar contraseña'}</button>
          <button type="button" className="secondary-button full-width" onClick={onLogout}>Volver al acceso</button>
        </form>
      </section>
    </main>
  );
}

function ProductsSection({ token }: { token: string }) {
  const [rows, setRows] = useState<ProductRow[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    api<ProductRow[]>('/tools/products', token)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'No se pudo cargar el catálogo');
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
      {error && <div className="alert error" role="alert">{error}</div>}
      {!error && rows === null && <div className="empty-state">Cargando catálogo…</div>}
      {!error && rows !== null && rows.length === 0 && (
        <div className="empty-state">No hay productos disponibles en esta instalación.</div>
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
                  <td>{row.category || '—'}</td>
                  <td>{row.unit_price.toFixed(2)} €</td>
                  <td>{row.available_stock}</td>
                  <td>{row.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function DocumentsSection({ token }: { token: string }) {
  const [rows, setRows] = useState<DocumentRow[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    api<{ documents: DocumentRow[] }>('/rag/documents', token)
      .then((data) => {
        if (!cancelled) setRows(data.documents);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'No se pudieron cargar los documentos');
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
      {error && <div className="alert error" role="alert">{error}</div>}
      {!error && rows === null && <div className="empty-state">Cargando documentos…</div>}
      {!error && rows !== null && rows.length === 0 && (
        <div className="empty-state">No hay documentos indexados en esta instalación.</div>
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
                  <td>{row.dlp_findings.length > 0 ? row.dlp_findings.join(', ') : '—'}</td>
                  <td>{row.created_at ? new Date(row.created_at).toLocaleString('es-ES') : '—'}</td>
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
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    api<{ agents: AgentRow[] }>('/agents', token)
      .then((data) => {
        if (!cancelled) setRows(data.agents);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'No se pudieron cargar los agentes');
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
      {error && <div className="alert error" role="alert">{error}</div>}
      {!error && rows === null && <div className="empty-state">Cargando agentes…</div>}
      {!error && rows !== null && rows.length === 0 && (
        <div className="empty-state">No hay agentes registrados en esta instalación.</div>
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
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    api<UserRow[]>('/users', token)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'No se pudieron cargar los usuarios');
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
      {!error && rows === null && <div className="empty-state">Cargando usuarios…</div>}
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
                  <td>{row.is_active ? 'Sí' : 'No'}</td>
                  <td>{row.must_change_password ? 'Sí' : 'No'}</td>
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
    <section id="automatizaciones" className="panel" aria-label="Automatizaciones">
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
          <span className={`status ${activepieces === 'configured' ? 'ok' : 'warning'}`}>
            <CheckCircle2 size={14} />
            {activepieces === 'configured' ? 'Configurado' : 'Pendiente de configuración'}
          </span>
        </div>
      </div>
      <div className="empty-state">
        El diseñador de automatizaciones no forma parte de la candidata core (Ruta A). Los flujos
        se ejecutan a través del bridge con validación, auditoría y aprobaciones; consulta la
        documentación de integraciones para habilitar Activepieces.
      </div>
    </section>
  );
}

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('agent_token') ?? '');
  const [username, setUsername] = useState(() => sessionStorage.getItem('agent_user') ?? '');
  const [mustChangePassword, setMustChangePassword] = useState(() => sessionStorage.getItem('agent_must_change') === 'true');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [costs, setCosts] = useState<CostSummary | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [section, setSection] = useState<SectionId>('resumen');
  const [theme, setTheme] = useState<'light' | 'dark'>(() => (localStorage.getItem('theme') as 'light' | 'dark') ?? 'light');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('theme', theme);
  }, [theme]);

  async function load() {
    if (!token) return;
    setLoading(true);
    setError('');
    try {
      const [dashboardData, costData, approvalData] = await Promise.all([
        api<Dashboard>('/provider/dashboard', token),
        api<CostSummary>('/costs', token),
        api<Approval[]>('/approvals?status_filter=pending', token),
      ]);
      setDashboard(dashboardData);
      setCosts(costData);
      setApprovals(approvalData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudieron cargar los datos');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function onLogin(nextToken: string, nextUsername: string, nextMustChange: boolean) {
    sessionStorage.setItem('agent_token', nextToken);
    sessionStorage.setItem('agent_user', nextUsername);
    sessionStorage.setItem('agent_must_change', String(nextMustChange));
    setToken(nextToken);
    setUsername(nextUsername);
    setMustChangePassword(nextMustChange);
  }

  async function logout() {
    if (token) {
      try {
        await api('/auth/logout', token, { method: 'POST' });
      } catch {
        // La sesión local debe cerrarse aunque el servidor no responda.
      }
    }
    sessionStorage.clear();
    setToken('');
    setUsername('');
    setMustChangePassword(false);
  }

  function passwordChanged() {
    sessionStorage.clear();
    setToken('');
    setUsername('');
    setMustChangePassword(false);
  }

  async function decide(id: string, decision: 'approve' | 'reject') {
    try {
      await api(`/approvals/${id}/${decision}`, token, {
        method: 'POST',
        body: JSON.stringify(decision === 'reject' ? { rejection_reason: 'Rechazada desde el panel' } : {}),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo registrar la decisión');
    }
  }

  const integrationRows = useMemo(() => Object.entries(dashboard?.integrations ?? {}), [dashboard]);

  if (!token) return <Login onLogin={onLogin} />;
  if (mustChangePassword) return <ChangePassword token={token} onComplete={passwordChanged} onLogout={() => void logout()} />;

  const navItems: Array<{ id: SectionId; label: string; icon: ReactNode }> = [
    { id: 'resumen', label: translations.nav.resumen, icon: <Gauge size={18} /> },
    { id: 'aprobaciones', label: translations.nav.aprobaciones, icon: <ShieldCheck size={18} /> },
    { id: 'catalogo', label: translations.nav.catalogo, icon: <Package size={18} /> },
    { id: 'documentos', label: translations.nav.documentos, icon: <FileText size={18} /> },
    { id: 'agentes', label: translations.nav.agentes, icon: <Bot size={18} /> },
    { id: 'automatizaciones', label: translations.nav.automatizaciones, icon: <Workflow size={18} /> },
    { id: 'usuarios', label: translations.nav.usuarios, icon: <Users size={18} /> },
  ];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark small">AI</div><div><strong>Agentes IA</strong><span>Control empresarial</span></div></div>
        <nav aria-label="Navegación principal">
          {navItems.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              className={section === item.id ? 'active' : ''}
              aria-current={section === item.id ? 'page' : undefined}
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
        <div className="sidebar-footer"><span>{username}</span><button onClick={() => void logout()} aria-label="Cerrar sesión"><LogOut size={17} /></button></div>
      </aside>

      <main className="content">
        <header className="topbar">
          <div><p>Instalación</p><h1>Resumen operativo</h1></div>
          <div className="topbar-actions">
            <button className="icon-button" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')} aria-label="Cambiar tema">
              {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
            </button>
            <button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''} />Actualizar</button>
          </div>
        </header>

        {dashboard?.pilot_mode && <div className="pilot-banner"><ShieldCheck size={18} />Modo piloto activo: las acciones sensibles requieren aprobación humana.</div>}
        {error && <div className="alert error" role="alert"><AlertTriangle size={18} />{error}</div>}

        <div hidden={section !== 'resumen'}>
          <section id="resumen" className="metrics-grid" aria-label="Indicadores principales">
            <article className="metric"><span>Productos</span><strong>{dashboard?.counts.products ?? '—'}</strong><Package size={20} /></article>
            <article className="metric"><span>Clientes</span><strong>{dashboard?.counts.customers ?? '—'}</strong><Users size={20} /></article>
            <article className="metric"><span>Pedidos</span><strong>{dashboard?.counts.orders ?? '—'}</strong><Boxes size={20} /></article>
            <article className="metric"><span>Aprobaciones pendientes</span><strong>{dashboard?.counts.pending_approvals ?? '—'}</strong><ShieldCheck size={20} /></article>
          </section>

          <section className="panel-grid">
            <article className="panel">
              <div className="panel-heading"><div><p>Estado técnico</p><h2>Integraciones</h2></div><Activity size={21} /></div>
              <div className="integration-list">
                {integrationRows.length === 0 && <div className="empty-state">No hay información disponible.</div>}
                {integrationRows.map(([name, state]) => (
                  <div className="integration-row" key={name}>
                    <span>{name === 'prestashop' ? 'PrestaShop' : name === 'ghl' ? 'GHL' : name === 'chatwoot' ? 'Chatwoot' : 'Activepieces'}</span>
                    <span className={`status ${state === 'configured' ? 'ok' : 'warning'}`}><CheckCircle2 size={14} />{state === 'configured' ? 'Configurado' : 'Pendiente de configuración'}</span>
                  </div>
                ))}
              </div>
            </article>

            <article className="panel">
              <div className="panel-heading"><div><p>Uso de inteligencia artificial</p><h2>Consumo y costes</h2></div><Activity size={21} /></div>
              <dl className="cost-list">
                <div><dt>Ejecuciones</dt><dd>{costs?.total_executions ?? '—'}</dd></div>
                <div><dt>Tokens</dt><dd>{costs?.total_tokens_consumed?.toLocaleString('es-ES') ?? '—'}</dd></div>
                <div><dt>Coste estimado</dt><dd>{costs ? `${costs.total_estimated_cost_usd.toFixed(4)} USD` : '—'}</dd></div>
                <div><dt>Ejecuciones simuladas</dt><dd>{costs?.simulated_executions ?? '—'}</dd></div>
              </dl>
            </article>
          </section>
        </div>

        <div hidden={section !== 'aprobaciones'}>
          <section id="aprobaciones" className="panel approvals-panel">
            <div className="panel-heading"><div><p>Control humano</p><h2>Aprobaciones pendientes</h2></div><span className="counter">{approvals.length}</span></div>
            {approvals.length === 0 ? (
              <div className="empty-state"><CheckCircle2 size={24} />No hay acciones pendientes de revisión.</div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Acción</th><th>Referencia</th><th>Fecha</th><th>Estado</th><th>Decisión</th></tr></thead>
                  <tbody>
                    {approvals.map((approval) => (
                      <tr key={approval.id}>
                        <td>{approval.action_type === 'issue_invoice' ? 'Aprobar borrador de factura' : approval.action_type}</td>
                        <td>{approval.target_key}</td>
                        <td>{new Date(approval.created_at).toLocaleString('es-ES')}</td>
                        <td><span className="status warning">Pendiente</span></td>
                        <td className="actions"><button className="success-button" onClick={() => void decide(approval.id, 'approve')}>Aprobar</button><button className="danger-button" onClick={() => void decide(approval.id, 'reject')}>Rechazar</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>

        <div hidden={section !== 'catalogo'}>
          <ProductsSection token={token} />
        </div>
        <div hidden={section !== 'documentos'}>
          <DocumentsSection token={token} />
        </div>
        <div hidden={section !== 'agentes'}>
          <AgentsSection token={token} />
        </div>
        <div hidden={section !== 'automatizaciones'}>
          <AutomationsSection dashboard={dashboard} />
        </div>
        <div hidden={section !== 'usuarios'}>
          <UsersSection token={token} />
        </div>
      </main>
    </div>
  );
}
