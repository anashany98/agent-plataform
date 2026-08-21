import { FormEvent, useEffect, useState } from "react";
import { apiRequest } from "./api";

export type EmailTemplate = {
  id: string;
  name: string;
  subject: string;
  body: string;
  signature: string | null;
  is_active: boolean;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type EmailSettings = {
  signature: string | null;
  tracking_enabled: boolean;
  updated_at: string | null;
};

export type TrackingEvent = {
  id: string;
  token: string;
  event_type: "sent" | "open" | "click";
  url: string | null;
  to: string | null;
  template_name: string | null;
  created_at: string | null;
};

type TemplateListResponse = {
  items: EmailTemplate[];
  variables: { key: string; label: string; description: string }[];
};

const EVENT_TYPE_LABELS: Record<string, string> = {
  sent: "Enviado",
  open: "Apertura",
  click: "Clic",
};

export function EmailSection({
  token,
  refreshRevision,
}: {
  token: string;
  refreshRevision: number;
}) {
  const [templates, setTemplates] = useState<EmailTemplate[] | null>(null);
  const [variables, setVariables] = useState<TemplateListResponse["variables"]>([]);
  const [, setSettings] = useState<EmailSettings | null>(null);
  const [events, setEvents] = useState<TrackingEvent[] | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionResult, setActionResult] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editSubject, setEditSubject] = useState("");
  const [editBody, setEditBody] = useState("");
  const [editSignature, setEditSignature] = useState("");
  // Formulario de alta.
  const [newName, setNewName] = useState("");
  const [newSubject, setNewSubject] = useState("");
  const [newBody, setNewBody] = useState("");
  const [creating, setCreating] = useState(false);
  // Settings.
  const [signature, setSignature] = useState("");
  const [trackingEnabled, setTrackingEnabled] = useState(true);
  const [savingSettings, setSavingSettings] = useState(false);

  async function loadAll() {
    setError("");
    try {
      const [templateData, settingsData, eventsData] = await Promise.all([
        apiRequest<TemplateListResponse>("/email/templates", { token }),
        apiRequest<EmailSettings>("/email/settings", { token }),
        apiRequest<{ items: TrackingEvent[] }>("/email/tracking/events", { token }),
      ]);
      setTemplates(templateData.items);
      setVariables(templateData.variables ?? []);
      setSettings(settingsData);
      setSignature(settingsData.signature ?? "");
      setTrackingEnabled(settingsData.tracking_enabled);
      setEvents(eventsData.items);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudieron cargar los datos de email",
      );
    }
  }

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, refreshRevision]);

  function flash(message: string) {
    setActionResult(message);
    window.setTimeout(() => setActionResult(""), 4_000);
  }

  async function createTemplate(event: FormEvent) {
    event.preventDefault();
    setActionError("");
    setCreating(true);
    try {
      await apiRequest<EmailTemplate>("/email/templates", {
        token,
        method: "POST",
        body: JSON.stringify({
          name: newName.trim(),
          subject: newSubject.trim(),
          body: newBody,
        }),
      });
      setNewName("");
      setNewSubject("");
      setNewBody("");
      flash("Plantilla creada. Cambio auditado.");
      await loadAll();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo crear la plantilla",
      );
    } finally {
      setCreating(false);
    }
  }

  function startEdit(template: EmailTemplate) {
    setEditingId(template.id);
    setEditSubject(template.subject);
    setEditBody(template.body);
    setEditSignature(template.signature ?? "");
  }

  async function saveEdit(template: EmailTemplate) {
    setActionError("");
    try {
      await apiRequest<EmailTemplate>(`/email/templates/${template.id}`, {
        token,
        method: "PATCH",
        body: JSON.stringify({
          subject: editSubject.trim(),
          body: editBody,
          signature: editSignature,
        }),
      });
      setEditingId(null);
      flash("Plantilla actualizada. Cambio auditado.");
      await loadAll();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo guardar la plantilla",
      );
    }
  }

  async function toggleActive(template: EmailTemplate) {
    setActionError("");
    try {
      await apiRequest<EmailTemplate>(`/email/templates/${template.id}`, {
        token,
        method: "PATCH",
        body: JSON.stringify({ is_active: !template.is_active }),
      });
      flash(template.is_active ? "Plantilla desactivada." : "Plantilla activada.");
      await loadAll();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo cambiar la plantilla",
      );
    }
  }

  async function deleteTemplate(template: EmailTemplate) {
    setActionError("");
    if (!window.confirm(`¿Eliminar la plantilla «${template.name}»?`)) {
      return;
    }
    try {
      await apiRequest<{ deleted: boolean }>(`/email/templates/${template.id}`, {
        token,
        method: "DELETE",
      });
      flash("Plantilla eliminada. Cambio auditado.");
      await loadAll();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo eliminar la plantilla",
      );
    }
  }

  async function sendTest(template: EmailTemplate) {
    setActionError("");
    const destination = window.prompt(
      `Email de destino para la prueba de «${template.name}»:`,
      "test@example.invalid",
    );
    if (!destination || !destination.trim()) return;
    try {
      const result = await apiRequest<{
        delivery_status: string;
        tracking_token: string | null;
      }>(`/email/templates/${template.id}/send-test`, {
        token,
        method: "POST",
        body: JSON.stringify({ to: destination.trim() }),
      });
      const trackingNote = result.tracking_token
        ? ` (tracking ${result.tracking_token.slice(0, 8)}…)`
        : " (sin tracking: falta EMAIL_TRACKING_BASE_URL)";
      flash(
        `Prueba encolada (${result.delivery_status})${trackingNote}. Cambio auditado.`,
      );
      await loadAll();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo enviar la prueba",
      );
    }
  }

  async function saveSettings(event: FormEvent) {
    event.preventDefault();
    setActionError("");
    setSavingSettings(true);
    try {
      await apiRequest<EmailSettings>("/email/settings", {
        token,
        method: "PUT",
        body: JSON.stringify({ signature, tracking_enabled: trackingEnabled }),
      });
      setSettings({ signature, tracking_enabled: trackingEnabled, updated_at: null });
      flash("Configuración de email guardada. Cambio auditado.");
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo guardar la configuración",
      );
    } finally {
      setSavingSettings(false);
    }
  }

  return (
    <section id="email" className="panel" aria-label="Email integrado">
      <div className="panel-heading">
        <div>
          <p>CRM · P2</p>
          <h2>Email integrado</h2>
        </div>
        <span className="counter">
          {templates?.length ?? 0} plantillas · {events?.length ?? 0} eventos
        </span>
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
      {!error && templates === null && (
        <div className="empty-state">Cargando plantillas…</div>
      )}

      {templates !== null && (
        <>
          <div className="table-wrap">
            <table>
              <caption className="sr-only">Plantillas de email</caption>
              <thead>
                <tr>
                  <th scope="col">Nombre</th>
                  <th scope="col">Asunto</th>
                  <th scope="col">Cuerpo</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {templates.length === 0 && (
                  <tr>
                    <td colSpan={5}>
                      <div className="empty-state">
                        Aún no hay plantillas. Crea la primera con el formulario;
                        el envío usa el pipeline existente (SMTP o spool local).
                      </div>
                    </td>
                  </tr>
                )}
                {templates.map((template) => (
                  <tr key={template.id}>
                    <td>
                      <strong>{template.name}</strong>
                    </td>
                    <td>
                      {editingId === template.id ? (
                        <input
                          aria-label={`Asunto de ${template.name}`}
                          value={editSubject}
                          maxLength={255}
                          onChange={(e) => setEditSubject(e.target.value)}
                        />
                      ) : (
                        template.subject
                      )}
                    </td>
                    <td>
                      {editingId === template.id ? (
                        <textarea
                          aria-label={`Cuerpo de ${template.name}`}
                          value={editBody}
                          rows={4}
                          onChange={(e) => setEditBody(e.target.value)}
                        />
                      ) : (
                        <span className="email-body-preview">
                          {template.body.split("\n")[0].slice(0, 80)}
                        </span>
                      )}
                      {editingId === template.id && (
                        <input
                          aria-label={`Firma de ${template.name}`}
                          placeholder="Firma propia (vacío = firma de instalación)"
                          value={editSignature}
                          onChange={(e) => setEditSignature(e.target.value)}
                        />
                      )}
                    </td>
                    <td>
                      <span
                        className={`status-pill ${template.is_active ? "ok" : ""}`}
                      >
                        {template.is_active ? "Activa" : "Inactiva"}
                      </span>
                    </td>
                    <td className="queue-actions">
                      {editingId === template.id ? (
                        <>
                          <button
                            type="button"
                            className="primary-button"
                            onClick={() => void saveEdit(template)}
                          >
                            Guardar
                          </button>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => setEditingId(null)}
                          >
                            Cancelar
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => void sendTest(template)}
                          >
                            Enviar prueba
                          </button>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => startEdit(template)}
                          >
                            Editar
                          </button>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => void toggleActive(template)}
                          >
                            {template.is_active ? "Desactivar" : "Activar"}
                          </button>
                          <button
                            type="button"
                            className="secondary-button danger"
                            onClick={() => void deleteTemplate(template)}
                          >
                            Eliminar
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <form
            className="kanban-editor"
            onSubmit={(event) => void createTemplate(event)}
          >
            <p>
              Nueva plantilla. Usa variables del catálogo:{" "}
              {variables.map((variable) => (
                <code key={variable.key} className="email-var">
                  {"{{" + variable.key + "}}"}
                </code>
              ))}
              . El tracking de apertura (pixel) y clics requiere
              EMAIL_TRACKING_BASE_URL configurado.
            </p>
            <div className="kanban-editor-add">
              <input
                value={newName}
                aria-label="Nombre de la nueva plantilla"
                placeholder="Nombre (p. ej. Seguimiento de presupuesto)"
                maxLength={120}
                onChange={(e) => setNewName(e.target.value)}
              />
              <input
                value={newSubject}
                aria-label="Asunto de la nueva plantilla"
                placeholder="Asunto con {{variables}}"
                maxLength={255}
                onChange={(e) => setNewSubject(e.target.value)}
              />
            </div>
            <textarea
              value={newBody}
              aria-label="Cuerpo de la nueva plantilla"
              placeholder="Cuerpo del correo (texto o HTML con {{variables}})"
              rows={4}
              onChange={(e) => setNewBody(e.target.value)}
            />
            <div className="kanban-editor-save">
              <button
                type="submit"
                className="primary-button"
                disabled={
                  creating ||
                  !newName.trim() ||
                  !newSubject.trim() ||
                  !newBody.trim()
                }
              >
                {creating ? "Creando…" : "Crear plantilla"}
              </button>
            </div>
          </form>
        </>
      )}

      <form
        className="kanban-editor"
        onSubmit={(event) => void saveSettings(event)}
      >
        <p>Firma de instalación (se añade al pie de los correos sin firma propia).</p>
        <textarea
          value={signature}
          aria-label="Firma de instalación"
          placeholder={"Un saludo,\nEquipo de ventas"}
          rows={2}
          onChange={(e) => setSignature(e.target.value)}
        />
        <div className="kanban-editor-save">
          <label>
            <input
              type="checkbox"
              checked={trackingEnabled}
              onChange={(e) => setTrackingEnabled(e.target.checked)}
            />{" "}
            Tracking de apertura y clics activo
          </label>
          <button type="submit" className="primary-button" disabled={savingSettings}>
            {savingSettings ? "Guardando…" : "Guardar configuración"}
          </button>
        </div>
      </form>

      {events !== null && (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Eventos de tracking de email</caption>
            <thead>
              <tr>
                <th scope="col">Evento</th>
                <th scope="col">Token</th>
                <th scope="col">Destino</th>
                <th scope="col">URL</th>
                <th scope="col">Plantilla</th>
                <th scope="col">Fecha</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 && (
                <tr>
                  <td colSpan={6}>
                    <div className="empty-state">
                      Aún no hay eventos de tracking. Envía un correo con
                      plantilla para ver aperturas y clics aquí.
                    </div>
                  </td>
                </tr>
              )}
              {events.map((event) => (
                <tr key={event.id}>
                  <td>
                    <span
                      className={`status-pill ${
                        event.event_type === "open"
                          ? "tracking-open"
                          : event.event_type === "click"
                            ? "tracking-click"
                            : ""
                      }`}
                    >
                      {EVENT_TYPE_LABELS[event.event_type] ?? event.event_type}
                    </span>
                  </td>
                  <td>
                    <code>{event.token}</code>
                  </td>
                  <td>{event.to ?? "—"}</td>
                  <td>
                    {event.url ? (
                      <code className="email-track-url">{event.url}</code>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{event.template_name ?? "—"}</td>
                  <td>
                    {event.created_at
                      ? new Date(event.created_at).toLocaleString()
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
