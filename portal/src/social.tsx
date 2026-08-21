import { FormEvent, useEffect, useState } from "react";
import { apiRequest } from "./api";

export type SocialTriage = {
  intent: string;
  language: string | null;
  register: string | null;
  sentiment: number | null;
  urgency: number | null;
  entities: Record<string, unknown>;
  score_social: number;
  summary: string | null;
  decided_by: string;
};

export type SocialMessage = {
  id: string;
  channel_id: string;
  thread_id: string | null;
  source_message_id: string;
  sender_handle: string | null;
  sender_name: string | null;
  email: string | null;
  phone: string | null;
  body: string;
  status: "pending_triage" | "triaged" | "dismissed" | "failed";
  lead_id: string | null;
  created_at: string | null;
  triage: SocialTriage | null;
};

export type SocialChannelRow = {
  id: string;
  name: string;
  channel: "generic" | "whatsapp";
  external_account_id: string | null;
  is_active: boolean;
  scopes: string[];
  secret_set: boolean;
  secret_prefix: string;
  verify_token_set: boolean;
  last_webhook_at: string | null;
  created_at: string | null;
};

type SocialStats = {
  by_status: Record<string, number>;
  by_channel: Record<string, number>;
  by_intent: Record<string, number>;
  avg_score_social: number;
};

const INTENT_LABELS: Record<string, string> = {
  lead: "Lead",
  queja: "Queja",
  consulta: "Consulta",
  spam: "Spam",
  otra: "Otro",
};

const STATUS_LABELS: Record<string, string> = {
  pending_triage: "Pendiente",
  triaged: "Triado",
  dismissed: "Descartado",
  failed: "Fallido",
};

const CHANNEL_LABELS: Record<string, string> = {
  generic: "Genérico (JSON+HMAC)",
  whatsapp: "WhatsApp Cloud API",
};

function intentBadge(intent: string): string {
  if (intent === "queja") return "badge badge-red";
  if (intent === "lead") return "badge badge-green";
  if (intent === "spam") return "badge badge-muted";
  return "badge badge-blue";
}

export function SocialSection({
  token,
  refreshRevision,
  isAdmin,
}: {
  token: string;
  refreshRevision: number;
  isAdmin: boolean;
}) {
  const [messages, setMessages] = useState<SocialMessage[] | null>(null);
  const [channels, setChannels] = useState<SocialChannelRow[] | null>(null);
  const [stats, setStats] = useState<SocialStats | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionResult, setActionResult] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [intentFilter, setIntentFilter] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  // Alta de canal (admin).
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newChannelType, setNewChannelType] = useState<"generic" | "whatsapp">("generic");
  const [newSecret, setNewSecret] = useState("");
  const [newVerifyToken, setNewVerifyToken] = useState("");

  const reload = () => {
    apiRequest<{ items: SocialMessage[] }>(
      `/social/inbox?limit=200${statusFilter ? `&status=${statusFilter}` : ""}${intentFilter ? `&intent=${intentFilter}` : ""}`,
      { token },
    )
      .then((data) => setMessages(data.items))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    apiRequest<SocialStats>("/social/stats", { token })
      .then(setStats)
      .catch(() => undefined);
    if (isAdmin) {
      apiRequest<{ items: SocialChannelRow[] }>("/social/channels", { token })
        .then((data) => setChannels(data.items))
        .catch(() => undefined);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, refreshRevision, statusFilter, intentFilter]);

  const dismiss = async (id: string) => {
    setBusyId(id);
    setActionError("");
    setActionResult("");
    try {
      await apiRequest(`/social/messages/${id}/dismiss`, { method: "POST", token });
      setActionResult("Mensaje descartado y auditado.");
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const createChannel = async (event: FormEvent) => {
    event.preventDefault();
    setCreating(true);
    setActionError("");
    setActionResult("");
    try {
      await apiRequest("/social/channels", {
        method: "POST",
        token,
        headers: { "Idempotency-Key": `soc-${crypto.randomUUID?.() ?? Date.now()}` },
        body: JSON.stringify({
          name: newName.trim(),
          channel: newChannelType,
          webhook_secret: newSecret.trim(),
          verify_token: newVerifyToken.trim() || null,
        }),
      });
      setActionResult("Canal creado. Configura el webhook con la URL y el secreto.");
      setNewName("");
      setNewSecret("");
      setNewVerifyToken("");
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  const toggleChannel = async (row: SocialChannelRow) => {
    setBusyId(row.id);
    setActionError("");
    try {
      await apiRequest(`/social/channels/${row.id}`, {
        method: "PATCH",
        token,
        body: JSON.stringify({ is_active: !row.is_active }),
      });
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const deleteChannel = async (row: SocialChannelRow) => {
    if (!window.confirm(`¿Eliminar el canal «${row.name}»?`)) return;
    setBusyId(row.id);
    setActionError("");
    setActionResult("");
    try {
      const result = await apiRequest<{ deleted: boolean; deactivated?: boolean }>(
        `/social/channels/${row.id}`,
        { method: "DELETE", token },
      );
      setActionResult(
        result.deactivated
          ? "El canal tenía mensajes: se desactivó (las evidencias del inbox se conservan)."
          : "Canal eliminado.",
      );
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const testChannel = async (row: SocialChannelRow) => {
    setBusyId(row.id);
    setActionError("");
    setActionResult("");
    try {
      const result = await apiRequest<{ message_id: string }>(
        `/social/channels/${row.id}/test`,
        { method: "POST", token },
      );
      setActionResult(`Mensaje de prueba triado (${result.message_id.slice(0, 8)}…).`);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const channelName = (id: string): string =>
    channels?.find((row) => row.id === id)?.name ?? id.slice(0, 8);

  return (
    <div className="section-card">
      <h3>Escucha social</h3>
      <p className="muted">
        Mensajes entrantes de WhatsApp y webhooks genéricos, triados de forma
        determinista a leads con actividad de seguimiento (SLA por canal).
      </p>
      {error && <div className="form-error">{error}</div>}
      {actionError && <div className="form-error">{actionError}</div>}
      {actionResult && <div className="form-success">{actionResult}</div>}

      {stats && (
        <div className="stat-row">
          <span>
            <strong>{Object.values(stats.by_status).reduce((a, b) => a + b, 0)}</strong> mensajes
          </span>
          <span>
            <strong>{stats.by_intent.lead ?? 0}</strong> leads
          </span>
          <span>
            <strong>{stats.by_intent.queja ?? 0}</strong> quejas
          </span>
          <span>
            <strong>{stats.avg_score_social}</strong> score social medio
          </span>
        </div>
      )}

      <div className="filter-row">
        <select
          aria-label="Filtrar por estado"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
        >
          <option value="">Todos los estados</option>
          {Object.entries(STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label="Filtrar por intención"
          value={intentFilter}
          onChange={(event) => setIntentFilter(event.target.value)}
        >
          <option value="">Todas las intenciones</option>
          {Object.entries(INTENT_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      <div className="inbox-list">
        {messages === null ? (
          <p className="muted">Cargando mensajes…</p>
        ) : messages.length === 0 ? (
          <p className="muted">No hay mensajes con estos filtros.</p>
        ) : (
          messages.map((message) => (
            <div key={message.id} className="inbox-item">
              <div className="inbox-item-head">
                <strong>
                  {message.sender_name || message.sender_handle || message.email || "Remitente desconocido"}
                </strong>
                <span className="muted">
                  {channelName(message.channel_id)} · {new Date(message.created_at ?? "").toLocaleString("es")}
                </span>
              </div>
              <p className="inbox-body">{message.body}</p>
              {message.triage && (
                <div className="triage-chips">
                  <span className={intentBadge(message.triage.intent)}>
                    {INTENT_LABELS[message.triage.intent] ?? message.triage.intent}
                  </span>
                  <span className="badge badge-blue">score {message.triage.score_social}</span>
                  <span className="badge badge-muted">
                    {message.triage.language === "en" ? "EN" : "ES"} · {message.triage.register}
                  </span>
                  {message.triage.urgency != null && message.triage.urgency >= 40 && (
                    <span className="badge badge-warn">urgente {message.triage.urgency}</span>
                  )}
                  <span className="badge badge-muted">{STATUS_LABELS[message.status]}</span>
                </div>
              )}
              {message.status !== "dismissed" && (
                <div className="inbox-actions">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    disabled={busyId === message.id}
                    onClick={() => dismiss(message.id)}
                  >
                    Descartar
                  </button>
                  {message.lead_id && (
                    <a className="btn-link" href={`#leads`}>
                      Lead vinculado
                    </a>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {isAdmin && (
        <>
          <h4>Canales</h4>
          {channels === null ? (
            <p className="muted">Cargando canales…</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Nombre</th>
                  <th>Tipo</th>
                  <th>Estado</th>
                  <th>Secreto</th>
                  <th>Último webhook</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {channels.map((row) => (
                  <tr key={row.id}>
                    <td>{row.name}</td>
                    <td>{CHANNEL_LABELS[row.channel] ?? row.channel}</td>
                    <td>
                  <span className={row.is_active ? "badge badge-green" : "badge badge-muted"}>
                    {row.is_active ? "Activo" : "Inactivo"}
                  </span>
                    </td>
                    <td className="muted">
                      {row.secret_set ? `${row.secret_prefix}••••` : "—"}
                    </td>
                    <td className="muted">
                      {row.last_webhook_at
                        ? new Date(row.last_webhook_at).toLocaleString("es")
                        : "Nunca"}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        disabled={busyId === row.id}
                        onClick={() => toggleChannel(row)}
                      >
                        {row.is_active ? "Desactivar" : "Activar"}
                      </button>{" "}
                      <button
                        type="button"
                        className="btn btn-secondary"
                        disabled={busyId === row.id}
                        onClick={() => testChannel(row)}
                      >
                        Probar
                      </button>{" "}
                      <button
                        type="button"
                        className="btn btn-danger"
                        disabled={busyId === row.id}
                        onClick={() => deleteChannel(row)}
                      >
                        Eliminar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h4>Nuevo canal</h4>
          <form className="inline-form" onSubmit={createChannel}>
            <input
              aria-label="Nombre del canal"
              placeholder="Nombre del canal"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              required
            />
            <select
              aria-label="Tipo de canal"
              value={newChannelType}
              onChange={(event) =>
                setNewChannelType(event.target.value as "generic" | "whatsapp")
              }
            >
              <option value="generic">Genérico (JSON+HMAC)</option>
              <option value="whatsapp">WhatsApp Cloud API</option>
            </select>
            <input
              aria-label="Secreto del webhook"
              type="password"
              placeholder="Secreto del webhook"
              value={newSecret}
              onChange={(event) => setNewSecret(event.target.value)}
              required
              minLength={8}
            />
            <input
              aria-label="Verify token"
              placeholder="Verify token (opcional)"
              value={newVerifyToken}
              onChange={(event) => setNewVerifyToken(event.target.value)}
            />
            <button type="submit" className="btn btn-primary" disabled={creating}>
              {creating ? "Creando…" : "Crear canal"}
            </button>
          </form>
          <p className="muted">
            URL del webhook: <code>/api/bridge/social/webhook/&lt;canal-id&gt;</code> — la firma y
            el challenge dependen del tipo de canal. El secreto nunca se devuelve por API.
          </p>
        </>
      )}
    </div>
  );
}
