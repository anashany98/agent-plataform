import { FormEvent, useEffect, useMemo, useState } from 'react';
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
  Search,
  ShieldCheck,
  Sun,
  Users,
  Workflow,
} from 'lucide-react';

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

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('agent_token') ?? '');
  const [username, setUsername] = useState(() => sessionStorage.getItem('agent_user') ?? '');
  const [mustChangePassword, setMustChangePassword] = useState(() => sessionStorage.getItem('agent_must_change') === 'true');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [costs, setCosts] = useState<CostSummary | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
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

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark small">AI</div><div><strong>Agentes IA</strong><span>Control empresarial</span></div></div>
        <nav aria-label="Navegación principal">
          <a href="#resumen" className="active"><Gauge size={18} />Resumen</a>
          <a href="#aprobaciones"><ShieldCheck size={18} />Aprobaciones</a>
          <a href="#catalogo"><Package size={18} />Productos</a>
          <a href="#documentos"><FileText size={18} />Documentos</a>
          <a href="#agentes"><Bot size={18} />Agentes de IA</a>
          <a href="#automatizaciones"><Workflow size={18} />Automatizaciones</a>
          <a href="#usuarios"><Users size={18} />Usuarios y permisos</a>
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
      </main>
    </div>
  );
}
