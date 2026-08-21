import { FormEvent, useEffect, useState } from "react";
import { apiRequest } from "./api";

export type ActivityRow = {
  id: string;
  lead_id: string | null;
  lead_email: string | null;
  lead_name: string | null;
  opportunity_id: string | null;
  opportunity_name: string | null;
  title: string;
  kind: string;
  description: string | null;
  due_at: string | null;
  remind_at: string | null;
  reminded_at: string | null;
  remind_email: string | null;
  status: string;
  assigned_to: string | null;
  assignee_username: string | null;
  completed_at: string | null;
  completed_by: string | null;
  created_at: string | null;
};

type LeadOption = {
  id: string;
  email: string;
  first_name: string;
  company_name: string | null;
};

type UserOption = {
  id: string;
  username: string;
  role: string;
};

export const KIND_LABELS: Record<string, string> = {
  call: "Llamada",
  meeting: "Reunión",
  follow_up: "Follow-up",
  email: "Email",
  note: "Nota",
  other: "Otro",
};

export const STATUS_LABELS: Record<string, string> = {
  pending: "Pendiente",
  done: "Hecha",
  cancelled: "Cancelada",
};

function formatWhen(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("es-ES", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ActivitiesSection({
  token,
  refreshRevision,
}: {
  token: string;
  refreshRevision: number;
}) {
  const [rows, setRows] = useState<ActivityRow[] | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionResult, setActionResult] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [leads, setLeads] = useState<LeadOption[]>([]);
  const [users, setUsers] = useState<UserOption[]>([]);
  const [form, setForm] = useState({
    title: "",
    kind: "follow_up",
    lead_id: "",
    due_at: "",
    remind_at: "",
    remind_email: "",
    assigned_to: "",
  });
  const [creating, setCreating] = useState(false);
  const [reminding, setReminding] = useState<string | null>(null);

  async function loadActivities() {
    setError("");
    try {
      const query = statusFilter
        ? `/activities?status=${encodeURIComponent(statusFilter)}`
        : "/activities";
      setRows(await apiRequest<ActivityRow[]>(query, { token }));
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudieron cargar las tareas",
      );
    }
  }

  useEffect(() => {
    void loadActivities();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshRevision, statusFilter, token]);

  useEffect(() => {
    let cancelled = false;
    apiRequest<LeadOption[]>("/leads", { token })
      .then((data) => {
        if (!cancelled) setLeads(Array.isArray(data) ? data : []);
      })
      .catch(() => undefined);
    apiRequest<UserOption[]>("/users", { token })
      .then((data) => {
        if (!cancelled) setUsers(Array.isArray(data) ? data : []);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function createActivity(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setActionError("");
    setActionResult("");
    try {
      await apiRequest<ActivityRow>("/activities", {
        token,
        method: "POST",
        body: JSON.stringify({
          title: form.title.trim(),
          kind: form.kind,
          lead_id: form.lead_id || null,
          due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
          remind_at: form.remind_at
            ? new Date(form.remind_at).toISOString()
            : null,
          remind_email: form.remind_email.trim() || null,
          assigned_to: form.assigned_to || null,
        }),
      });
      setActionResult("Tarea creada. Cambio auditado.");
      setForm({
        title: "",
        kind: "follow_up",
        lead_id: "",
        due_at: "",
        remind_at: "",
        remind_email: "",
        assigned_to: "",
      });
      await loadActivities();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo crear la tarea",
      );
    } finally {
      setCreating(false);
    }
  }

  async function changeStatus(activity: ActivityRow, status: string) {
    setActionError("");
    setActionResult("");
    try {
      await apiRequest<ActivityRow>(`/activities/${activity.id}`, {
        token,
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setActionResult(
        status === "done"
          ? `«${activity.title}» completada.`
          : `«${activity.title}» cancelada.`,
      );
      await loadActivities();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo actualizar la tarea",
      );
    }
  }

  async function remindNow(activity: ActivityRow) {
    setActionError("");
    setActionResult("");
    setReminding(activity.id);
    try {
      const result = await apiRequest<{
        delivery_status: string;
        provider: string;
      }>(`/activities/${activity.id}/remind`, { token, method: "POST" });
      setActionResult(
        result.delivery_status === "queued_for_manual_delivery"
          ? `Recordatorio de «${activity.title}» en cola de entrega (${result.provider}).`
          : `Recordatorio de «${activity.title}» enviado.`,
      );
      await loadActivities();
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : "No se pudo enviar el recordatorio",
      );
    } finally {
      setReminding(null);
    }
  }

  const visibleRows = rows ?? [];

  return (
    <section
      id="activities"
      className="panel"
      aria-label="Actividades de comercial"
    >
      <div className="panel-heading">
        <div>
          <p>CRM local · T-044</p>
          <h2>Tareas y recordatorios</h2>
        </div>
        <div className="kanban-actions">
          <label className="filter-label">
            Estado
            <select
              value={statusFilter}
              aria-label="Filtrar por estado"
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">Todos</option>
              <option value="pending">Pendientes</option>
              <option value="done">Hechas</option>
              <option value="cancelled">Canceladas</option>
            </select>
          </label>
          <span className="counter">{visibleRows.length}</span>
        </div>
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {actionError && (
        <div className="alert error" role="alert">
          {actionError}
        </div>
      )}
      {actionResult && (
        <div className="alert info" role="status">
          {actionResult}
        </div>
      )}
      {!error && rows === null && (
        <div className="empty-state">Cargando tareas…</div>
      )}

      {!error && rows !== null && rows.length === 0 && (
        <div className="empty-state">
          No hay tareas con este filtro. Crea la primera con el formulario.
        </div>
      )}

      {!error && rows !== null && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Actividades de comercial</caption>
            <thead>
              <tr>
                <th scope="col">Tarea</th>
                <th scope="col">Lead</th>
                <th scope="col">Vence</th>
                <th scope="col">Recordatorio</th>
                <th scope="col">Estado</th>
                <th scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((activity) => (
                <tr key={activity.id}>
                  <td>
                    <strong>{activity.title}</strong>
                    <br />
                    <small>
                      {KIND_LABELS[activity.kind] ?? activity.kind}
                      {activity.opportunity_name
                        ? ` · ${activity.opportunity_name}`
                        : ""}
                    </small>
                  </td>
                  <td>
                    {activity.lead_name ?? "—"}
                    <br />
                    <small>{activity.lead_email ?? ""}</small>
                  </td>
                  <td>{formatWhen(activity.due_at)}</td>
                  <td>
                    {activity.remind_at ? (
                      <>
                        {formatWhen(activity.remind_at)}
                        <br />
                        <small>
                          {activity.reminded_at
                            ? `recordado ${formatWhen(activity.reminded_at)}`
                            : `a ${activity.remind_email ?? activity.lead_email ?? "—"}`}
                        </small>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>
                    <span className={`status-pill status-${activity.status}`}>
                      {STATUS_LABELS[activity.status] ?? activity.status}
                    </span>
                  </td>
                  <td className="queue-actions">
                    {activity.status === "pending" && (
                      <>
                        <button
                          type="button"
                          className="secondary-button"
                          disabled={reminding === activity.id}
                          onClick={() => void remindNow(activity)}
                        >
                          {reminding === activity.id
                            ? "Enviando…"
                            : "Recordar ahora"}
                        </button>
                        <button
                          type="button"
                          className="success-button"
                          onClick={() => void changeStatus(activity, "done")}
                        >
                          Completar
                        </button>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() =>
                            void changeStatus(activity, "cancelled")
                          }
                        >
                          Cancelar
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form
        className="import-form"
        onSubmit={(event) => void createActivity(event)}
        aria-label="Nueva tarea"
        aria-busy={creating}
      >
        <p>Nueva tarea</p>
        <div className="import-grid">
          <label>
            Título
            <input
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              required
              maxLength={255}
            />
          </label>
          <label>
            Tipo
            <select
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value })}
            >
              {Object.entries(KIND_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Lead
            <select
              value={form.lead_id}
              onChange={(e) => setForm({ ...form, lead_id: e.target.value })}
            >
              <option value="">Sin vincular…</option>
              {leads.map((lead) => (
                <option key={lead.id} value={lead.id}>
                  {lead.first_name}
                  {lead.company_name ? ` (${lead.company_name})` : ""} ·{" "}
                  {lead.email}
                </option>
              ))}
            </select>
          </label>
          <label>
            Vence
            <input
              type="datetime-local"
              value={form.due_at}
              onChange={(e) => setForm({ ...form, due_at: e.target.value })}
            />
          </label>
          <label>
            Recordar en
            <input
              type="datetime-local"
              value={form.remind_at}
              onChange={(e) => setForm({ ...form, remind_at: e.target.value })}
            />
          </label>
          <label>
            Email del recordatorio
            <input
              type="email"
              value={form.remind_email}
              placeholder="Por defecto: email del lead"
              onChange={(e) =>
                setForm({ ...form, remind_email: e.target.value })
              }
            />
          </label>
          <label>
            Comercial
            <select
              value={form.assigned_to}
              onChange={(e) =>
                setForm({ ...form, assigned_to: e.target.value })
              }
            >
              <option value="">Sin asignar…</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.username} ({user.role})
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="primary-button" disabled={creating}>
            {creating ? "Creando…" : "Crear tarea"}
          </button>
        </div>
      </form>
    </section>
  );
}
