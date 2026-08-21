import { useEffect, useRef, useState } from "react";
import { apiRequest } from "./api";
import type { CustomFieldDefinition } from "./customFields";

export type TimelineEntry = {
  kind: string;
  title: string;
  detail: string;
  created_at: string | null;
  actor: string | null;
  opportunity_name?: string | null;
};

export type LeadTimelineData = {
  lead: {
    id: string;
    email: string;
    first_name: string;
    company_name: string | null;
    source: string;
    status: string;
    created_at: string | null;
  };
  timeline: TimelineEntry[];
};

type CustomValueRow = {
  field: CustomFieldDefinition;
  value: unknown;
  updated_at: string | null;
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

function LeadCustomFields({ token, leadId }: { token: string; leadId: string }) {
  const [rows, setRows] = useState<CustomValueRow[] | null>(null);
  const [error, setError] = useState("");
  const [drafts, setDrafts] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState("");

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError("");
    setDrafts({});
    apiRequest<CustomValueRow[]>(
      `/custom-values?entity_type=lead&entity_id=${encodeURIComponent(leadId)}`,
      { token },
    )
      .then((result) => {
        if (!cancelled) setRows(result);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error ? err.message : "No se pudieron cargar los campos",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [leadId, token]);

  const dirty = Object.keys(drafts).length > 0;

  async function saveAll() {
    setSaving(true);
    setError("");
    try {
      for (const [fieldId, value] of Object.entries(drafts)) {
        await apiRequest("/custom-values", {
          token,
          method: "PUT",
          headers: { "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify({
            entity_type: "lead",
            entity_id: leadId,
            field_id: fieldId,
            value,
          }),
        });
      }
      setDrafts({});
      setSavedFlash("Campos guardados.");
      window.setTimeout(() => setSavedFlash(""), 4_000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron guardar los campos");
    } finally {
      setSaving(false);
    }
  }

  if (rows === null && !error) return null;
  if (rows && rows.length === 0 && !dirty) return null;

  return (
    <div className="timeline drawer-custom-fields">
      <h3>Campos personalizados</h3>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {rows && rows.length === 0 && (
        <div className="empty-state">
          Esta instalación aún no tiene campos personalizados para leads.
        </div>
      )}
      {rows && rows.length > 0 && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void saveAll();
          }}
        >
          <dl className="approval-details drawer-details">
            {rows.map((row) => {
              const draft =
                row.field.id in drafts ? drafts[row.field.id] : row.value;
              return (
                <div key={row.field.id}>
                  <dt>
                    {row.field.label}
                    {row.field.required ? " *" : ""}
                  </dt>
                  <dd>
                    {row.field.field_type === "boolean" ? (
                      <input
                        type="checkbox"
                        aria-label={row.field.label}
                        checked={Boolean(draft)}
                        onChange={(e) =>
                          setDrafts((current) => ({
                            ...current,
                            [row.field.id]: e.target.checked,
                          }))
                        }
                      />
                    ) : row.field.field_type === "select" ? (
                      <select
                        aria-label={row.field.label}
                        value={draft === null || draft === undefined ? "" : String(draft)}
                        onChange={(e) =>
                          setDrafts((current) => ({
                            ...current,
                            [row.field.id]: e.target.value === "" ? null : e.target.value,
                          }))
                        }
                      >
                        <option value="">—</option>
                        {(row.field.options ?? []).map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type={
                          row.field.field_type === "number"
                            ? "number"
                            : row.field.field_type === "date"
                              ? "date"
                              : "text"
                        }
                        aria-label={row.field.label}
                        value={draft === null || draft === undefined ? "" : String(draft)}
                        onChange={(e) =>
                          setDrafts((current) => ({
                            ...current,
                            [row.field.id]:
                              row.field.field_type === "number"
                                ? e.target.value === ""
                                  ? null
                                  : Number(e.target.value)
                                : e.target.value === ""
                                  ? null
                                  : e.target.value,
                          }))
                        }
                      />
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
          <div className="drawer-custom-fields-actions">
            <button
              type="submit"
              className="primary-button"
              disabled={!dirty || saving}
            >
              {saving ? "Guardando…" : "Guardar campos"}
            </button>
            {savedFlash && (
              <span className="alert info" role="status">
                {savedFlash}
              </span>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

export function LeadTimelineDrawer({
  token,
  leadId,
  onClose,
}: {
  token: string;
  leadId: string | null;
  onClose: () => void;
}) {
  const [data, setData] = useState<LeadTimelineData | null>(null);
  const [error, setError] = useState("");
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!leadId) return;
    let cancelled = false;
    setData(null);
    setError("");
    apiRequest<LeadTimelineData>(`/leads/${leadId}/timeline`, { token })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error ? err.message : "No se pudo cargar la ficha",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [leadId, token]);

  useEffect(() => {
    if (leadId) closeRef.current?.focus();
  }, [leadId, data]);

  useEffect(() => {
    if (!leadId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [leadId, onClose]);

  if (!leadId) return null;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="lead-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Ficha del lead"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="drawer-head">
          <div>
            <p>Ficha del lead</p>
            <h2>{data?.lead.first_name || "Cargando…"}</h2>
          </div>
          <button
            ref={closeRef}
            type="button"
            className="secondary-button"
            onClick={onClose}
            aria-label="Cerrar ficha"
          >
            ✕
          </button>
        </div>

        {error && (
          <div className="alert error" role="alert">
            {error}
          </div>
        )}
        {!error && data === null && (
          <div className="empty-state">Cargando ficha…</div>
        )}

        {!error && data && (
          <>
            <dl className="approval-details drawer-details">
              <div>
                <dt>Email</dt>
                <dd>{data.lead.email}</dd>
              </div>
              {data.lead.company_name && (
                <div>
                  <dt>Empresa</dt>
                  <dd>{data.lead.company_name}</dd>
                </div>
              )}
              <div>
                <dt>Origen</dt>
                <dd>{data.lead.source}</dd>
              </div>
              <div>
                <dt>Estado</dt>
                <dd>{data.lead.status}</dd>
              </div>
              <div>
                <dt>Alta</dt>
                <dd>{formatWhen(data.lead.created_at)}</dd>
              </div>
            </dl>

            <LeadCustomFields token={token} leadId={leadId} />

            <div className="timeline">
              <h3>Historial</h3>
              {data.timeline.length === 0 && (
                <div className="empty-state">
                  Sin interacciones registradas todavía.
                </div>
              )}
              <ol className="timeline-list">
                {data.timeline.map((entry, index) => (
                  <li
                    key={`${entry.kind}-${index}-${entry.created_at ?? ""}`}
                    className={`timeline-item timeline-${entry.kind}`}
                  >
                    <div className="timeline-marker" aria-hidden="true" />
                    <div className="timeline-body">
                      <div className="timeline-title">
                        <strong>{entry.title}</strong>
                        {entry.opportunity_name && (
                          <span className="timeline-opp">
                            {entry.opportunity_name}
                          </span>
                        )}
                      </div>
                      <p className="timeline-detail">{entry.detail}</p>
                      <span className="timeline-meta">
                        {formatWhen(entry.created_at)}
                        {entry.actor ? ` · ${entry.actor}` : ""}
                      </span>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
