import { FormEvent, useEffect, useState } from "react";
import { apiRequest } from "./api";

export type CampaignStats = {
  total: number;
  sent: number;
  failed: number;
  queued: number;
  skipped: number;
  pending: number;
  opened: number;
  clicked: number;
  bounced: number;
  opened_rate: number;
  clicked_rate: number;
  bounce_rate: number;
};

export type Campaign = {
  id: string;
  name: string;
  description: string | null;
  template_name: string;
  segment: Record<string, unknown>;
  status: "draft" | "active" | "sent" | "cancelled" | "pending_retry";
  scheduled_at: string | null;
  sent_at: string | null;
  created_by: string | null;
  created_at: string | null;
  stats: CampaignStats;
};

export type CampaignRecipient = {
  id: string;
  lead_id: string;
  email: string;
  first_name: string | null;
  status: "pending" | "sent" | "failed" | "queued" | "skipped";
  error: string | null;
  tracking_token: string | null;
  opened: boolean;
  clicked: boolean;
  bounced: boolean;
  sent_at: string | null;
};

type CampaignDetail = Campaign & { recipients: CampaignRecipient[] };

const STATUS_LABELS: Record<string, string> = {
  draft: "Borrador",
  active: "Activa",
  sent: "Enviada",
  cancelled: "Cancelada",
  pending_retry: "Pendiente de reintento",
};

const RECIPIENT_LABELS: Record<string, string> = {
  pending: "Pendiente",
  sent: "Enviado",
  failed: "Fallido",
  queued: "En reintento",
  skipped: "Omitido",
};

const SOURCES = ["web", "chat", "form", "referral", "import", "local"];

const SOURCE_LABELS: Record<string, string> = {
  web: "Web",
  chat: "Chat",
  form: "Formulario",
  referral: "Referido",
  import: "Importado",
  local: "Local",
};

const OPS = ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "is_set", "is_empty"];

const OP_LABELS: Record<string, string> = {
  eq: "=",
  neq: "≠",
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  contains: "contiene",
  is_set: "tiene valor",
  is_empty: "vacío",
};

type SegmentDraft = {
  score_min: string;
  score_max: string;
  sources: string[];
  custom_fields: { key: string; op: string; value: string }[];
};

const EMPTY_SEGMENT: SegmentDraft = {
  score_min: "",
  score_max: "",
  sources: [],
  custom_fields: [],
};

export function CampaignsSection({
  token,
  refreshRevision,
}: {
  token: string;
  refreshRevision: number;
}) {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [templates, setTemplates] = useState<{ id: string; name: string }[]>([]);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionResult, setActionResult] = useState("");

  // Alta.
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newTemplate, setNewTemplate] = useState("");
  const [segment, setSegment] = useState<SegmentDraft>(EMPTY_SEGMENT);
  // Preview.
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<{ count: number; sample: unknown[] } | null>(null);
  // Detalle.
  const [detail, setDetail] = useState<CampaignDetail | null>(null);
  const [sendingId, setSendingId] = useState<string | null>(null);

  async function load() {
    setError("");
    try {
      const [campaignData, templateData] = await Promise.all([
        apiRequest<{ campaigns: Campaign[] }>("/campaigns", { token }),
        apiRequest<{ items: { id: string; name: string }[] }>("/email/templates", {
          token,
        }),
      ]);
      setCampaigns(campaignData.campaigns);
      setTemplates(templateData.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar las campañas");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshRevision, token]);

  async function createCampaign(event: FormEvent) {
    event.preventDefault();
    setActionError("");
    setActionResult("");
    setPreview(null);
    if (!newName.trim() || !newTemplate) {
      setActionError("Indica el nombre y elige una plantilla de email activa.");
      return;
    }
    const payload: Record<string, unknown> = {
      name: newName.trim(),
      description: newDescription.trim() || null,
      template_name: newTemplate,
    };
    const segmentPayload: Record<string, unknown> = {};
    if (segment.score_min !== "") segmentPayload.score_min = Number(segment.score_min);
    if (segment.score_max !== "") segmentPayload.score_max = Number(segment.score_max);
    if (segment.sources.length > 0) segmentPayload.sources = segment.sources;
    const custom = segment.custom_fields.filter((row) => row.key.trim() !== "");
    if (custom.length > 0) {
      segmentPayload.custom_fields = custom.map((row) => ({
        key: row.key.trim(),
        op: row.op,
        value: row.op === "is_set" || row.op === "is_empty" ? null : row.value,
      }));
    }
    payload.segment = segmentPayload;
    setCreating(true);
    try {
      await apiRequest<Campaign>("/campaigns", {
        token,
        method: "POST",
        body: JSON.stringify(payload),
        headers: { "Idempotency-Key": `portal-campaign-${Date.now()}-${Math.random().toString(36).slice(2)}` },
      });
      setActionResult(`Campaña «${newName.trim()}» creada como borrador.`);
      setNewName("");
      setNewDescription("");
      setNewTemplate("");
      setSegment(EMPTY_SEGMENT);
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "No se pudo crear la campaña");
    } finally {
      setCreating(false);
    }
  }

  async function previewSegment() {
    if (!detail && !campaigns) return;
    setPreviewing(true);
    setActionError("");
    setPreview(null);
    const target = detail ?? campaigns?.find((c) => c.id === previewId);
    if (!target) {
      setPreviewing(false);
      return;
    }
    try {
      const data = await apiRequest<{ count: number; sample: unknown[] }>(
        `/campaigns/${target.id}/preview`,
        { token, method: "POST" },
      );
      setPreview(data);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "No se pudo evaluar el segmento");
    } finally {
      setPreviewing(false);
    }
  }

  const [previewId, setPreviewId] = useState<string | null>(null);

  async function openDetail(campaignId: string) {
    setActionError("");
    setPreview(null);
    try {
      const data = await apiRequest<CampaignDetail>(`/campaigns/${campaignId}`, { token });
      setDetail(data);
      setPreviewId(campaignId);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "No se pudo abrir la campaña");
    }
  }

  async function sendCampaign(campaignId: string) {
    if (!window.confirm("¿Enviar esta campaña a todos los leads del segmento? La operación es definitiva.")) {
      return;
    }
    setSendingId(campaignId);
    setActionError("");
    setActionResult("");
    try {
      const data = await apiRequest<CampaignStats & { recipients?: number; sent?: number; failed?: number; skipped?: number }>(
        `/campaigns/${campaignId}/send`,
        { token, method: "POST" },
      );
      setActionResult(
        `Envío completado: ${data.sent ?? 0} enviados, ${data.failed ?? 0} fallidos, ${data.skipped ?? 0} omitidos.`,
      );
      await load();
      if (detail?.id === campaignId) await openDetail(campaignId);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "No se pudo enviar la campaña");
    } finally {
      setSendingId(null);
    }
  }

  async function cancelCampaign(campaignId: string) {
    if (!window.confirm("¿Cancelar esta campaña? No se enviará.")) return;
    setActionError("");
    try {
      await apiRequest<{ deleted: string }>(`/campaigns/${campaignId}`, {
        token,
        method: "DELETE",
      });
      setActionResult("Campaña cancelada.");
      if (detail?.id === campaignId) setDetail(null);
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "No se pudo cancelar la campaña");
    }
  }

  function toggleSource(source: string) {
    setSegment((prev) => ({
      ...prev,
      sources: prev.sources.includes(source)
        ? prev.sources.filter((item) => item !== source)
        : [...prev.sources, source],
    }));
  }

  function updateCriterion(index: number, patch: Partial<{ key: string; op: string; value: string }>) {
    setSegment((prev) => ({
      ...prev,
      custom_fields: prev.custom_fields.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    }));
  }

  return (
    <section id="campanas" className="panel" aria-label="Campañas segmentadas">
      <div className="panel-heading">
        <div>
          <p>Email marketing</p>
          <h2>Campañas segmentadas</h2>
        </div>
        <p className="muted">
          Envía plantillas existentes a un segmento de leads (score, fuente o campos
          personalizados) con tracking de apertura/clics por destinatario.
        </p>
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

      <form className="campaign-form" onSubmit={createCampaign}>
        <h3>Nueva campaña</h3>
        <div className="form-grid">
          <label>
            Nombre
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Ej.: Oferta septiembre logística"
              required
            />
          </label>
          <label>
            Plantilla de email (activa)
            <select
              value={newTemplate}
              onChange={(e) => setNewTemplate(e.target.value)}
              required
            >
              <option value="">Selecciona una plantilla…</option>
              {templates.map((template) => (
                <option key={template.id} value={template.name}>
                  {template.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label>
          Descripción
          <textarea
            value={newDescription}
            onChange={(e) => setNewDescription(e.target.value)}
            rows={2}
            placeholder="Objetivo de la campaña (opcional)"
          />
        </label>

        <h4>Segmento (todo opcional; vacío = todos los leads activos)</h4>
        <div className="form-grid">
          <label>
            Score mínimo (0-100)
            <input
              type="number"
              min={0}
              max={100}
              value={segment.score_min}
              onChange={(e) => setSegment({ ...segment, score_min: e.target.value })}
            />
          </label>
          <label>
            Score máximo (0-100)
            <input
              type="number"
              min={0}
              max={100}
              value={segment.score_max}
              onChange={(e) => setSegment({ ...segment, score_max: e.target.value })}
            />
          </label>
        </div>
        <fieldset className="campaign-sources">
          <legend>Fuente del lead</legend>
          {SOURCES.map((source) => (
            <label key={source} className="check">
              <input
                type="checkbox"
                checked={segment.sources.includes(source)}
                onChange={() => toggleSource(source)}
              />
              {SOURCE_LABELS[source] ?? source}
            </label>
          ))}
        </fieldset>
        <div className="campaign-criteria">
          {segment.custom_fields.map((row, index) => (
            <div key={index} className="criteria-row">
              <input
                aria-label="Clave del campo"
                value={row.key}
                onChange={(e) => updateCriterion(index, { key: e.target.value })}
                placeholder="campo (key)"
              />
              <select
                aria-label="Operador"
                value={row.op}
                onChange={(e) => updateCriterion(index, { op: e.target.value })}
              >
                {OPS.map((op) => (
                  <option key={op} value={op}>
                    {OP_LABELS[op]}
                  </option>
                ))}
              </select>
              {row.op !== "is_set" && row.op !== "is_empty" && (
                <input
                  aria-label="Valor"
                  value={row.value}
                  onChange={(e) => updateCriterion(index, { value: e.target.value })}
                  placeholder="valor"
                />
              )}
              <button
                type="button"
                className="ghost-button danger"
                onClick={() =>
                  setSegment({
                    ...segment,
                    custom_fields: segment.custom_fields.filter((_, i) => i !== index),
                  })
                }
              >
                Quitar
              </button>
            </div>
          ))}
          <button
            type="button"
            className="ghost-button"
            onClick={() =>
              setSegment({
                ...segment,
                custom_fields: [...segment.custom_fields, { key: "", op: "eq", value: "" }],
              })
            }
          >
            + Criterio de campo personalizado
          </button>
        </div>
        <div className="form-actions">
          <button type="submit" className="primary-button" disabled={creating}>
            {creating ? "Creando…" : "Crear campaña (borrador)"}
          </button>
        </div>
      </form>

      <div className="campaign-list">
        <h3>Campañas</h3>
        {campaigns === null ? (
          <p className="muted">Cargando…</p>
        ) : campaigns.length === 0 ? (
          <p className="muted">Todavía no hay campañas.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Nombre</th>
                <th scope="col">Estado</th>
                <th scope="col">Destinatarios</th>
                <th scope="col">Enviados</th>
                <th scope="col">Abiertos</th>
                <th scope="col">Clics</th>
                <th scope="col">Rebotados</th>
                <th scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((campaign) => (
                <tr key={campaign.id}>
                  <td>
                    <strong>{campaign.name}</strong>
                    {campaign.description && (
                      <div className="muted small">{campaign.description}</div>
                    )}
                  </td>
                  <td>
                    <span className={`badge status-${campaign.status}`}>
                      {STATUS_LABELS[campaign.status] ?? campaign.status}
                    </span>
                  </td>
                  <td>{campaign.stats.total}</td>
                  <td>{campaign.stats.sent}</td>
                  <td>{campaign.stats.opened}</td>
                  <td>{campaign.stats.clicked}</td>
                  <td>{campaign.stats.bounced}</td>
                  <td className="row-actions">
                    <button type="button" className="ghost-button" onClick={() => void openDetail(campaign.id)}>
                      Detalle
                    </button>
                    {(campaign.status === "draft" || campaign.status === "pending_retry") && (
                      <>
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() => void sendCampaign(campaign.id)}
                          disabled={sendingId === campaign.id}
                        >
                          {sendingId === campaign.id ? "Enviando…" : "Reenviar"}
                        </button>
                        <button
                          type="button"
                          className="ghost-button danger"
                          onClick={() => void cancelCampaign(campaign.id)}
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
        )}
      </div>

      {detail && (
        <div className="campaign-detail">
          <div className="panel-heading">
            <div>
              <h3>{detail.name}</h3>
              <p className="muted">
                Plantilla: {detail.template_name} · {STATUS_LABELS[detail.status] ?? detail.status}
                {detail.sent_at ? ` · enviada ${new Date(detail.sent_at).toLocaleString()}` : ""}
              </p>
            </div>
            <button type="button" className="ghost-button" onClick={() => setDetail(null)}>
              Cerrar detalle
            </button>
          </div>
          <div className="stats-pills">
            <span className="pill">Total {detail.stats.total}</span>
            <span className="pill">Enviados {detail.stats.sent}</span>
            <span className="pill">Abiertos {detail.stats.opened}</span>
            <span className="pill">Clics {detail.stats.clicked}</span>
            <span className="pill">Rebotados {detail.stats.bounced}</span>
            <span className="pill">Fallidos {detail.stats.failed}</span>
            {detail.stats.queued > 0 && <span className="pill">En cola {detail.stats.queued}</span>}
            <span className="pill">Omitidos {detail.stats.skipped}</span>
          </div>
          {detail.stats.sent > 0 && (
            <div className="deliverability">
              <h4>Entregabilidad</h4>
              <p className="muted">
                Tasa de apertura <strong>{detail.stats.opened_rate}%</strong>
                <span aria-hidden="true"> · </span>
                Tasa de clics <strong>{detail.stats.clicked_rate}%</strong>
                <span aria-hidden="true"> · </span>
                Tasa de rebote <strong>{detail.stats.bounce_rate}%</strong>
                <span aria-hidden="true"> · </span>
                Entregados <strong>{detail.stats.sent - detail.stats.bounced}</strong> de {detail.stats.sent}
              </p>
            </div>
          )}
          <div className="form-actions">
            <button
              type="button"
              className="ghost-button"
              onClick={() => void previewSegment()}
              disabled={previewing}
            >
              {previewing ? "Evaluando…" : "Probar segmento (cuenta)"}
            </button>
            {preview && (
              <span className="muted">
                El segmento alcanza <strong>{preview.count}</strong> leads
                {preview.sample.length > 0 &&
                  `, p. ej. ${(preview.sample as { first_name?: string; email?: string }[])
                    .map((lead) => lead.first_name ?? lead.email ?? "")
                    .filter(Boolean)
                    .join(", ")}`}
                .
              </span>
            )}
          </div>
          <h4>Destinatarios</h4>
          {detail.recipients.length === 0 ? (
            <p className="muted">Todavía no hay destinatarios (envía la campaña para materializarlos).</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Email</th>
                  <th scope="col">Nombre</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Apertura</th>
                  <th scope="col">Clic</th>
                  <th scope="col">Rebote</th>
                </tr>
              </thead>
              <tbody>
                {detail.recipients.map((recipient) => (
                  <tr key={recipient.id}>
                    <td>{recipient.email}</td>
                    <td>{recipient.first_name ?? "—"}</td>
                    <td>
                      <span className={`badge status-${recipient.status}`}>
                        {RECIPIENT_LABELS[recipient.status] ?? recipient.status}
                      </span>
                      {recipient.error && <span className="muted small"> ({recipient.error})</span>}
                    </td>
                    <td>{recipient.opened ? "✓" : "—"}</td>
                    <td>{recipient.clicked ? "✓" : "—"}</td>
                    <td>{recipient.bounced ? "✓" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}
