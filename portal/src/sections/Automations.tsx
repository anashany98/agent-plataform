/**
 * Sección Automatizaciones: el motor real del Bridge, en lenguaje llano.
 *
 * Muestra la última actividad de cada automatización del motor (recordatorios
 * de presupuesto, cobros vencidos, alerta de stock y carrito abandonado), el
 * estado de la cola de envíos y permite al admin disparar un ciclo «Ejecutar
 * ahora» sin jerga técnica. La nota de Activepieces queda al pie: el diseñador
 * externo no forma parte de la candidata core; los flujos corren en el Bridge
 * con validación, auditoría y aprobaciones.
 */

import { FormEvent, useEffect, useState } from "react";
import { Play, RefreshCw, Sparkles, Workflow } from "lucide-react";
import { apiRequest } from "../api";

type EngineEntry = {
  last_run_at: string | null;
  last_status: string | null;
  last_summary: string | null;
};

type DeadLetterEntry = {
  id: string;
  topic: string;
  topic_label: string;
  created_at: string | null;
  attempt_count: number;
  max_attempts: number;
  permanent: boolean;
  reason: string;
};

type AutomationsStatus = {
  engine: {
    quote_expiry: EngineEntry | null;
    dunning: EngineEntry | null;
    low_stock: EngineEntry | null;
    cart_abandonment: EngineEntry | null;
  };
  queue: { pending: number; dead: number };
  scheduled_tasks: { active: number; paused: number };
  dead_letter: DeadLetterEntry[] | null;
};

const ENGINE_CARDS: Array<{
  key: keyof AutomationsStatus["engine"];
  title: string;
  description: string;
}> = [
  {
    key: "quote_expiry",
    title: "Recordatorios de presupuesto",
    description: "Recuerda a los clientes que su presupuesto está a punto de caducar.",
  },
  {
    key: "dunning",
    title: "Avisos de cobro vencido",
    description: "Envía recordatorios de facturas sin pagar, sin cobrar nada por su cuenta.",
  },
  {
    key: "low_stock",
    title: "Alerta de stock bajo",
    description: "Avisa cuando un producto se queda por debajo del mínimo.",
  },
  {
    key: "cart_abandonment",
    title: "Carritos olvidados",
    description: "Da un toque a los presupuestos empezados y no confirmados.",
  },
];

function formatLastRun(iso: string | null): string {
  if (!iso) return "Todavía no se ha ejecutado";
  const deltaMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.max(0, Math.floor(deltaMs / 60000));
  if (minutes < 1) return "hace menos de un minuto";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.floor(hours / 24)} d`;
}

function entryLine(entry: EngineEntry | null): string {
  if (!entry) return "Todavía no se ha ejecutado";
  const when = formatLastRun(entry.last_run_at);
  if (!entry.last_summary) return `Última ejecución ${when}`;
  return `Última ejecución ${when} · ${entry.last_summary}`;
}

export function AutomationsSection({
  token,
  canWrite,
  refreshRevision,
}: {
  token: string;
  canWrite: boolean;
  refreshRevision: number;
}) {
  const [status, setStatus] = useState<AutomationsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState("");
  const [retrying, setRetrying] = useState<string | null>(null);
  const [queueNotice, setQueueNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    apiRequest<AutomationsStatus>("/automations/status", { token })
      .then((data) => {
        if (!cancelled) setStatus(data);
      })
      .catch(() => {
        if (!cancelled) setError("No se pudo consultar el estado del motor.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, refreshRevision]);

  async function runSweep(event: FormEvent) {
    event.preventDefault();
    if (!canWrite || running) return;
    setRunning(true);
    setRunResult("");
    try {
      const data = await apiRequest<{
        quote_expiry: { reminded: number; failed: number };
        dunning: { delivered: number; failed: number };
      }>("/automations/sweep", { token, method: "POST" });
      const quote = data.quote_expiry ?? {};
      const dunning = data.dunning ?? {};
      const total = (quote.reminded ?? 0) + (dunning.delivered ?? 0);
      const failures = (quote.failed ?? 0) + (dunning.failed ?? 0);
      setRunResult(
        `Ejecutado: ${total} aviso(s) enviado(s), ${failures} error(es).`,
      );
      const fresh = await apiRequest<AutomationsStatus>("/automations/status", { token });
      setStatus(fresh);
    } catch {
      setRunResult("No se pudo ejecutar ahora. Revisa la conexión e inténtalo de nuevo.");
    } finally {
      setRunning(false);
    }
  }

  async function retryMessage(id: string) {
    if (!canWrite || retrying) return;
    setRetrying(id);
    setQueueNotice("");
    try {
      await apiRequest(`/outbox/${id}/retry`, { token, method: "POST" });
      setQueueNotice("Reencolado: se reintentará automáticamente.");
      const fresh = await apiRequest<AutomationsStatus>("/automations/status", {
        token,
      });
      setStatus(fresh);
    } catch {
      setQueueNotice("No se pudo reencolar. Inténtalo de nuevo.");
    } finally {
      setRetrying(null);
    }
  }

  const queue =
    (status?.queue.pending ?? 0) + (status?.queue.dead ?? 0) > 0
      ? `${status!.queue.pending} en cola de reintento, ${status!.queue.dead} fallados definitivamente`
      : "nada pendiente";

  return (
    <section id="automatizaciones" className="panel" aria-label="Automatizaciones">
      <div className="panel-heading">
        <div>
          <p>Trabajo automático</p>
          <h2>Automatizaciones</h2>
        </div>
        <Workflow size={21} />
      </div>
      <p className="muted">
        Estas tareas se encargan solas de lo repetitivo. Puedes ver cuándo se
        ejecutaron por última vez y, si algo se retrasa, dispararlas con un
        clic.
      </p>

      {loading && <p className="muted">Cargando estado…</p>}
      {error && <p className="alert">{error}</p>}

      {status && (
        <div className="integration-list">
          {ENGINE_CARDS.map((card) => {
            const entry = status.engine[card.key];
            return (
              <div className="integration-row" key={card.key}>
                <div>
                  <span>{card.title}</span>
                  <span className="muted block">{card.description}</span>
                </div>
                <span className="status ok">
                  <Sparkles size={14} />
                  {entryLine(entry)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {canWrite && (
        <form className="form-actions" onSubmit={runSweep}>
          <button type="submit" className="primary-button" disabled={running}>
            {running ? <RefreshCw className="spin" size={16} /> : <Play size={16} />}
            {running ? "Ejecutando…" : "Ejecutar ahora"}
          </button>
          {runResult && <span className="muted">{runResult}</span>}
        </form>
      )}

      {canWrite &&
        status?.dead_letter &&
        status.dead_letter.length > 0 && (
          <div className="dlq-section">
            <h3>Envíos que fallaron</h3>
            <p className="muted">
              Estos envíos no pudieron completarse. Puedes reintentarlos con
              un clic; si el problema sigue, revisa la integración señalada en
              el motivo.
            </p>
            {queueNotice && (
              <div className="notice-box" role="status">
                {queueNotice}
              </div>
            )}
            <div className="resource-list">
              {status.dead_letter.map((entry) => (
                <article className="resource-card" key={entry.id}>
                  <div>
                    <strong>{entry.topic_label}</strong>
                    <span className="badge badge-red">fallado</span>
                  </div>
                  <p className="muted">{entry.reason}</p>
                  <span className="muted">
                    Se intentó {entry.attempt_count} de {entry.max_attempts}{" "}
                    veces
                    {entry.created_at
                      ? ` · ${formatLastRun(entry.created_at)}`
                      : ""}
                  </span>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={retrying === entry.id}
                    onClick={() => void retryMessage(entry.id)}
                  >
                    {retrying === entry.id ? "Reencolando…" : "Reintentar"}
                  </button>
                </article>
              ))}
            </div>
          </div>
        )}

      <div className="empty-state">
        <p>
          <strong>Envíos pendientes:</strong> {queue}.{" "}
          <strong>Tareas programadas:</strong> {status?.scheduled_tasks.active ?? 0}{" "}
          activas, {status?.scheduled_tasks.paused ?? 0} pausadas.
        </p>
        <p className="muted">
          El diseñador de flujos externo (Activepieces) no forma parte de la
          candidata core: los flujos se ejecutan en el Bridge con validación,
          auditoría y aprobaciones. Consulta la documentación de integraciones
          para habilitarlo.
        </p>
      </div>
    </section>
  );
}
