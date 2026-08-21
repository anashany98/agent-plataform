import { FormEvent, useEffect, useState } from "react";
import { apiRequest } from "./api";

export type WebhookEventCatalogItem = {
  key: string;
  label: string;
  description: string;
};

export type WebhookSubscription = {
  id: string;
  name: string;
  url: string;
  events: string[];
  is_active: boolean;
  secret_set: boolean;
  secret_prefix: string;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
};

type WebhookListResponse = {
  items: WebhookSubscription[];
  event_catalog: WebhookEventCatalogItem[];
};

const EVENT_LABELS: Record<string, string> = {
  "lead.created": "Lead creado",
  "lead.assigned": "Lead asignado",
  "pipeline.stage_changed": "Cambio de etapa",
  "quote.confirmed": "Presupuesto confirmado",
};

const EVENT_KEYS = [
  "lead.created",
  "lead.assigned",
  "pipeline.stage_changed",
  "quote.confirmed",
];

export function WebhooksSection({
  token,
  refreshRevision,
}: {
  token: string;
  refreshRevision: number;
}) {
  const [items, setItems] = useState<WebhookSubscription[] | null>(null);
  const [catalog, setCatalog] = useState<WebhookEventCatalogItem[]>([]);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionResult, setActionResult] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  // Formulario de alta.
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [newSecret, setNewSecret] = useState("");
  const [newEvents, setNewEvents] = useState<string[]>(["lead.created"]);
  const [newActive, setNewActive] = useState(true);
  const [creating, setCreating] = useState(false);
  // Edición en línea.
  const [editName, setEditName] = useState("");
  const [editUrl, setEditUrl] = useState("");
  const [editSecret, setEditSecret] = useState("");
  const [editEvents, setEditEvents] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  async function loadSubscriptions() {
    setError("");
    try {
      const data = await apiRequest<WebhookListResponse>(
        "/webhooks/subscriptions",
        { token },
      );
      setItems(data.items);
      setCatalog(data.event_catalog ?? []);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "No se pudieron cargar las suscripciones",
      );
    }
  }

  useEffect(() => {
    void loadSubscriptions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, refreshRevision]);

  function flash(message: string) {
    setActionResult(message);
    window.setTimeout(() => setActionResult(""), 4_000);
  }

  function toggleEvent(selected: string[], event: string): string[] {
    return selected.includes(event)
      ? selected.filter((item) => item !== event)
      : [...selected, event];
  }

  async function createSubscription(event: FormEvent) {
    event.preventDefault();
    setActionError("");
    if (newEvents.length === 0) {
      setActionError("Selecciona al menos un evento.");
      return;
    }
    setCreating(true);
    try {
      await apiRequest<WebhookSubscription>("/webhooks/subscriptions", {
        token,
        method: "POST",
        body: JSON.stringify({
          name: newName.trim(),
          url: newUrl.trim(),
          secret: newSecret,
          events: newEvents,
          is_active: newActive,
        }),
      });
      setNewName("");
      setNewUrl("");
      setNewSecret("");
      setNewEvents(["lead.created"]);
      setNewActive(true);
      flash("Suscripción creada. Cambio auditado.");
      await loadSubscriptions();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo crear la suscripción",
      );
    } finally {
      setCreating(false);
    }
  }

  function startEdit(subscription: WebhookSubscription) {
    setEditingId(subscription.id);
    setEditName(subscription.name);
    setEditUrl(subscription.url);
    setEditSecret("");
    setEditEvents(subscription.events);
  }

  async function saveEdit(subscription: WebhookSubscription) {
    setActionError("");
    if (editEvents.length === 0) {
      setActionError("Selecciona al menos un evento.");
      return;
    }
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        name: editName.trim(),
        url: editUrl.trim(),
        events: editEvents,
      };
      if (editSecret.trim()) {
        payload.secret = editSecret.trim();
      }
      await apiRequest<WebhookSubscription>(
        `/webhooks/subscriptions/${subscription.id}`,
        { token, method: "PATCH", body: JSON.stringify(payload) },
      );
      setEditingId(null);
      flash("Suscripción actualizada. Cambio auditado.");
      await loadSubscriptions();
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : "No se pudo guardar la suscripción",
      );
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(subscription: WebhookSubscription) {
    setActionError("");
    try {
      await apiRequest<WebhookSubscription>(
        `/webhooks/subscriptions/${subscription.id}`,
        {
          token,
          method: "PATCH",
          body: JSON.stringify({ is_active: !subscription.is_active }),
        },
      );
      flash(
        subscription.is_active
          ? "Suscripción desactivada: los envíos pendientes se omiten."
          : "Suscripción activada.",
      );
      await loadSubscriptions();
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : "No se pudo cambiar la suscripción",
      );
    }
  }

  async function deleteSubscription(subscription: WebhookSubscription) {
    setActionError("");
    if (!window.confirm(`¿Eliminar la suscripción «${subscription.name}»?`)) {
      return;
    }
    try {
      await apiRequest<{ deleted: boolean }>(
        `/webhooks/subscriptions/${subscription.id}`,
        { token, method: "DELETE" },
      );
      flash("Suscripción eliminada. Cambio auditado.");
      await loadSubscriptions();
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : "No se pudo eliminar la suscripción",
      );
    }
  }

  async function testSubscription(subscription: WebhookSubscription) {
    setActionError("");
    setActionResult("");
    try {
      const result = await apiRequest<{ status: string; outbox_id: string }>(
        `/webhooks/subscriptions/${subscription.id}/test`,
        { token, method: "POST" },
      );
      flash(
        `Evento de prueba encolado (${result.outbox_id.slice(0, 8)}…). El envío lo intenta el worker del outbox.`,
      );
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo encolar la prueba",
      );
    }
  }

  function eventCheckbox(
    events: string[],
    setEvents: (events: string[]) => void,
    event: string,
  ) {
    return (
      <label key={event} className="webhook-event-label">
        <input
          type="checkbox"
          checked={events.includes(event)}
          onChange={() => setEvents(toggleEvent(events, event))}
        />
        {EVENT_LABELS[event] ?? event}
      </label>
    );
  }

  return (
    <section id="webhooks" className="panel" aria-label="Webhooks salientes">
      <div className="panel-heading">
        <div>
          <p>CRM · P2-f</p>
          <h2>Webhooks salientes</h2>
        </div>
        <span className="counter">{items?.length ?? 0} suscripciones</span>
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
      {!error && items === null && (
        <div className="empty-state">Cargando suscripciones…</div>
      )}

      {items !== null && (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">
              Suscripciones de webhooks salientes
            </caption>
            <thead>
              <tr>
                <th scope="col">Nombre</th>
                <th scope="col">URL</th>
                <th scope="col">Eventos</th>
                <th scope="col">Estado</th>
                <th scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr>
                  <td colSpan={5}>
                    <div className="empty-state">
                      Aún no hay suscripciones. Crea la primera con el
                      formulario; el envío va firmado por HMAC y pasa por el
                      outbox durable.
                    </div>
                  </td>
                </tr>
              )}
              {items.map((subscription) => (
                <tr key={subscription.id}>
                  <td>
                    {editingId === subscription.id ? (
                      <input
                        aria-label="Nombre de la suscripción"
                        value={editName}
                        maxLength={120}
                        onChange={(e) => setEditName(e.target.value)}
                      />
                    ) : (
                      <>
                        <strong>{subscription.name}</strong>
                        <small className="webhook-secret-hint">
                          {" "}
                          firma {subscription.secret_prefix}…{" "}
                          {subscription.secret_set ? "✓" : "sin secreto"}
                        </small>
                      </>
                    )}
                  </td>
                  <td>
                    {editingId === subscription.id ? (
                      <input
                        aria-label="URL de la suscripción"
                        value={editUrl}
                        maxLength={1024}
                        onChange={(e) => setEditUrl(e.target.value)}
                      />
                    ) : (
                      <code>{subscription.url}</code>
                    )}
                  </td>
                  <td>
                    {editingId === subscription.id ? (
                      <div className="webhook-events">
                        {EVENT_KEYS.map((event) =>
                          eventCheckbox(editEvents, setEditEvents, event),
                        )}
                        {editSecret && (
                          <div className="webhook-secret-edit">
                            <input
                              aria-label="Nuevo secreto de la suscripción"
                              placeholder="Nuevo secreto (mín. 16 caracteres)"
                              value={editSecret}
                              maxLength={512}
                              onChange={(e) => setEditSecret(e.target.value)}
                            />
                          </div>
                        )}
                      </div>
                    ) : (
                      subscription.events
                        .map((event) => EVENT_LABELS[event] ?? event)
                        .join(", ")
                    )}
                  </td>
                  <td>
                    <span
                      className={`status-pill ${subscription.is_active ? "ok" : ""}`}
                    >
                      {subscription.is_active ? "Activa" : "Inactiva"}
                    </span>
                  </td>
                  <td className="queue-actions">
                    {editingId === subscription.id ? (
                      <>
                        <button
                          type="button"
                          className="primary-button"
                          disabled={saving}
                          onClick={() => void saveEdit(subscription)}
                        >
                          {saving ? "Guardando…" : "Guardar"}
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
                          onClick={() => void testSubscription(subscription)}
                        >
                          Probar
                        </button>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => startEdit(subscription)}
                        >
                          Editar
                        </button>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => void toggleActive(subscription)}
                        >
                          {subscription.is_active ? "Desactivar" : "Activar"}
                        </button>
                        <button
                          type="button"
                          className="secondary-button danger"
                          onClick={() => void deleteSubscription(subscription)}
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
      )}

      <form
        className="kanban-editor"
        onSubmit={(event) => void createSubscription(event)}
      >
        <p>
          Nueva suscripción. El payload se firma con HMAC-SHA256 usando el
          secreto de la suscripción y se entrega por el outbox durable
          (reintentos con backoff y dead-letter auditada). Las URL de redes
          privadas se rechazan (anti-SSRF).
        </p>
        <div className="kanban-editor-add">
          <input
            value={newName}
            aria-label="Nombre de la nueva suscripción"
            placeholder="Nombre (p. ej. CRM externo)"
            maxLength={120}
            onChange={(e) => setNewName(e.target.value)}
          />
          <input
            value={newUrl}
            aria-label="URL de la nueva suscripción"
            placeholder="https://…/hook"
            maxLength={1024}
            onChange={(e) => setNewUrl(e.target.value)}
          />
          <input
            value={newSecret}
            aria-label="Secreto HMAC de la nueva suscripción"
            placeholder="Secreto (mín. 16 caracteres)"
            maxLength={512}
            onChange={(e) => setNewSecret(e.target.value)}
          />
        </div>
        <div className="webhook-events">
          {EVENT_KEYS.map((event) =>
            eventCheckbox(newEvents, setNewEvents, event),
          )}
        </div>
        <div className="kanban-editor-save">
          <label>
            <input
              type="checkbox"
              checked={newActive}
              onChange={(e) => setNewActive(e.target.checked)}
            />{" "}
            Activa al crearla
          </label>
          <button
            type="submit"
            className="primary-button"
            disabled={
              creating ||
              !newName.trim() ||
              !newUrl.trim() ||
              newSecret.trim().length < 16 ||
              newEvents.length === 0
            }
          >
            {creating ? "Creando…" : "Crear suscripción"}
          </button>
        </div>
      </form>

      {catalog.length > 0 && (
        <details className="webhook-catalog">
          <summary>Eventos disponibles</summary>
          <ul>
            {catalog.map((event) => (
              <li key={event.key}>
                <code>{event.key}</code> — {event.label}. {event.description}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
