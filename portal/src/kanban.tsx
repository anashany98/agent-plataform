import {
  DragEvent,
  FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { apiRequest } from "./api";
import { LeadTimelineDrawer } from "./timeline";

export type PipelineStage = {
  key: string;
  name: string;
  position: number;
  probability: number;
};

export type KanbanCard = {
  id: string;
  lead_id: string;
  name: string;
  stage: string;
  status: string;
  monetary_value: number;
  currency: string;
  probability: number | null;
  external_reference: string | null;
  notes_count: number;
  lead_email: string | null;
  lead_first_name: string | null;
  lead_company: string | null;
  assigned_to: string | null;
  created_at: string | null;
};

export const LOST_REASONS = [
  "Precio demasiado alto",
  "Presupuesto insuficiente",
  "Competencia más barata",
  "Decisión aplazada",
  "Sin necesidad real",
  "Contacto perdido",
  "Otro",
];

export type ScoreSignal = {
  kind: string;
  points: number;
  detail: string;
};

export type UnassignedLead = {
  id: string;
  email: string;
  first_name: string;
  company_name: string | null;
  source: string;
  status: string;
  opportunities: KanbanCard[];
  score: number;
  score_signals: ScoreSignal[];
  created_at: string | null;
};

export type KanbanUser = {
  id: string;
  username: string;
  role: string;
};

export type PipelineBoard = {
  stages: Array<PipelineStage & { opportunities: KanbanCard[] }>;
  unassigned_leads: UnassignedLead[];
  users: KanbanUser[];
};

function formatValue(value: number, currency: string): string {
  return `${Number.isFinite(value) ? value.toFixed(2) : "—"} ${currency}`;
}

function Card({
  card,
  dragging,
  onDragStart,
  onDragEnd,
  onOpenDetail,
  onClose,
}: {
  card: KanbanCard;
  dragging: boolean;
  onDragStart: (event: DragEvent<HTMLDivElement>, card: KanbanCard) => void;
  onDragEnd: () => void;
  onOpenDetail: (leadId: string) => void;
  onClose: (card: KanbanCard) => void;
}) {
  const terminal =
    card.stage === "won" ||
    card.stage === "lost" ||
    card.status === "won" ||
    card.status === "lost";
  return (
    <div
      className={`kanban-card${dragging ? " dragging" : ""}${terminal ? " terminal" : ""}`}
      draggable={!terminal}
      onDragStart={(event) => onDragStart(event, card)}
      onDragEnd={onDragEnd}
      onClick={() => onOpenDetail(card.lead_id)}
      role="button"
      tabIndex={0}
      aria-label={`${card.name} — ${formatValue(card.monetary_value, card.currency)}. Abrir ficha del lead`}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpenDetail(card.lead_id);
        }
      }}
    >
      <strong className="kanban-card-title">{card.name}</strong>
      <span className="kanban-card-client">
        {card.lead_first_name ?? card.lead_email ?? "Sin cliente"}
        {card.lead_company ? ` · ${card.lead_company}` : ""}
      </span>
      <span className="kanban-card-value">
        {formatValue(card.monetary_value, card.currency)}
      </span>
      {card.probability !== null && card.probability !== undefined && (
        <span className="kanban-card-prob">{card.probability}%</span>
      )}
      {card.assigned_to && (
        <span className="kanban-card-assignee">→ {card.assigned_to}</span>
      )}
      {!terminal && (
        <button
          type="button"
          className="secondary-button kanban-close-btn"
          onClick={(event) => {
            event.stopPropagation();
            onClose(card);
          }}
        >
          Cerrar
        </button>
      )}
    </div>
  );
}

export function KanbanSection({
  token,
  isAdmin,
  refreshRevision,
}: {
  token: string;
  isAdmin: boolean;
  refreshRevision: number;
}) {
  const [board, setBoard] = useState<PipelineBoard | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionResult, setActionResult] = useState("");
  const [dragFrom, setDragFrom] = useState<KanbanCard | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [movingId, setMovingId] = useState<string | null>(null);
  // Modo edición de etapas (solo admin).
  const [editing, setEditing] = useState(false);
  const [editNames, setEditNames] = useState<string[]>([]);
  const [newStageName, setNewStageName] = useState("");
  const [savingStages, setSavingStages] = useState(false);
  const [assigningLead, setAssigningLead] = useState<string | null>(null);
  const [detailLeadId, setDetailLeadId] = useState<string | null>(null);
  // Cierre de oportunidad (T-054): ganada/perdida con motivo.
  const [closingCard, setClosingCard] = useState<KanbanCard | null>(null);
  const [closeOutcome, setCloseOutcome] = useState<"won" | "lost">("won");
  const [closeReason, setCloseReason] = useState("");
  const [closeProbability, setCloseProbability] = useState("");
  const [savingClose, setSavingClose] = useState(false);
  const flashTimer = useRef<number | null>(null);

  async function loadBoard() {
    setError("");
    try {
      const data = await apiRequest<PipelineBoard>("/pipeline/board", {
        token,
      });
      setBoard(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudo cargar el pipeline",
      );
    }
  }

  useEffect(() => {
    void loadBoard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshRevision, token]);

  useEffect(() => {
    return () => {
      if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    };
  }, []);

  function flash(message: string) {
    setActionResult(message);
    if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setActionResult(""), 4_000);
  }

  async function moveCard(card: KanbanCard, targetStage: string) {
    if (card.stage === targetStage) return;
    setActionError("");
    setMovingId(card.id);
    try {
      const result = await apiRequest<{
        id: string;
        stage: string;
        changed: boolean;
      }>(`/opportunities/${card.id}`, {
        token,
        method: "PATCH",
        body: JSON.stringify({ stage: targetStage }),
      });
      if (result.changed) {
        flash(`«${card.name}» movida a ${targetStage}. Cambio auditado.`);
      }
      await loadBoard();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo mover la oportunidad",
      );
      await loadBoard();
    } finally {
      setMovingId(null);
    }
  }

  function onDragStart(event: DragEvent<HTMLDivElement>, card: KanbanCard) {
    setDragFrom(card);
    setActionError("");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", card.id);
  }

  function onDropOnStage(event: DragEvent<HTMLDivElement>, stageKey: string) {
    event.preventDefault();
    setDropTarget(null);
    if (dragFrom) void moveCard(dragFrom, stageKey);
  }

  async function assignLead(leadId: string, userId: string | null) {
    setActionError("");
    setAssigningLead(leadId);
    try {
      await apiRequest<{ id: string; assigned_to: string | null }>(
        `/leads/${leadId}/assign`,
        {
          token,
          method: "PATCH",
          body: JSON.stringify({ user_id: userId }),
        },
      );
      flash(
        userId === null
          ? "Lead desasignado."
          : "Lead asignado. Cambio auditado.",
      );
      await loadBoard();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo asignar el lead",
      );
      await loadBoard();
    } finally {
      setAssigningLead(null);
    }
  }

  function startEditing() {
    if (!board) return;
    setEditNames(board.stages.map((stage) => stage.name));
    setEditing(true);
  }

  function openCloseModal(card: KanbanCard) {
    setClosingCard(card);
    setCloseOutcome("won");
    setCloseReason("");
    setCloseProbability("");
    setActionError("");
  }

  async function submitClose(event: FormEvent) {
    event.preventDefault();
    if (!closingCard) return;
    setActionError("");
    setSavingClose(true);
    try {
      const result = await apiRequest<{
        id: string;
        stage: string;
        status: string;
        probability: number;
        lost_reason: string | null;
        won_at: string | null;
        lost_at: string | null;
      }>(`/opportunities/${closingCard.id}/close`, {
        token,
        method: "POST",
        body: JSON.stringify({
          outcome: closeOutcome,
          lost_reason:
            closeOutcome === "lost" && closeReason.trim()
              ? closeReason.trim()
              : null,
          probability:
            closeProbability.trim() !== "" ? Number(closeProbability) : null,
        }),
      });
      flash(
        closeOutcome === "won"
          ? `«${closingCard.name}» marcada como ganada (${result.probability}%).`
          : `«${closingCard.name}» marcada como perdida. Cambio auditado.`,
      );
      setClosingCard(null);
      await loadBoard();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo cerrar la oportunidad",
      );
    } finally {
      setSavingClose(false);
    }
  }

  async function saveStages(event: FormEvent) {
    event.preventDefault();
    setActionError("");
    setSavingStages(true);
    try {
      await apiRequest<PipelineStage[]>("/pipeline/stages", {
        token,
        method: "PUT",
        body: JSON.stringify({ names: editNames }),
      });
      setEditing(false);
      flash("Pipeline actualizado. Cambio auditado.");
      await loadBoard();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo guardar el pipeline",
      );
    } finally {
      setSavingStages(false);
    }
  }

  const columns = useMemo(() => board?.stages ?? [], [board]);
  const unassigned = board?.unassigned_leads ?? [];
  const users = board?.users ?? [];

  return (
    <section
      id="pipeline"
      className="panel"
      aria-label="Pipeline comercial (kanban)"
    >
      <div className="panel-heading">
        <div>
          <p>CRM local · P1-a</p>
          <h2>Pipeline comercial</h2>
        </div>
        <div className="kanban-actions">
          <span className="counter">{columns.length} etapas</span>
          {isAdmin && !editing && (
            <button
              type="button"
              className="secondary-button"
              onClick={startEditing}
            >
              Editar etapas
            </button>
          )}
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
      {!error && board === null && (
        <div className="empty-state">Cargando pipeline…</div>
      )}

      {editing && board !== null && (
        <form
          className="kanban-editor"
          onSubmit={(event) => void saveStages(event)}
        >
          <p>
            Nombres de las etapas en orden. Las claves estables se conservan y
            las oportunidades de etapas eliminadas vuelven a la primera.
          </p>
          <div className="kanban-editor-list">
            {editNames.map((name, index) => (
              <div className="kanban-editor-row" key={index}>
                <span className="kanban-editor-index">{index + 1}</span>
                <input
                  value={name}
                  aria-label={`Nombre de la etapa ${index + 1}`}
                  maxLength={120}
                  onChange={(e) => {
                    const next = [...editNames];
                    next[index] = e.target.value;
                    setEditNames(next);
                  }}
                />
                <div className="kanban-editor-moves">
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={index === 0}
                    aria-label={`Subir etapa ${name}`}
                    onClick={() => {
                      const next = [...editNames];
                      [next[index - 1], next[index]] = [
                        next[index],
                        next[index - 1],
                      ];
                      setEditNames(next);
                    }}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={index === editNames.length - 1}
                    aria-label={`Bajar etapa ${name}`}
                    onClick={() => {
                      const next = [...editNames];
                      [next[index + 1], next[index]] = [
                        next[index],
                        next[index + 1],
                      ];
                      setEditNames(next);
                    }}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={editNames.length <= 2}
                    aria-label={`Eliminar etapa ${name}`}
                    onClick={() => {
                      setEditNames(editNames.filter((_, i) => i !== index));
                    }}
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))}
          </div>
          <div className="kanban-editor-add">
            <input
              value={newStageName}
              aria-label="Nombre de la nueva etapa"
              maxLength={120}
              placeholder="Nueva etapa…"
              onChange={(e) => setNewStageName(e.target.value)}
            />
            <button
              type="button"
              className="secondary-button"
              disabled={!newStageName.trim()}
              onClick={() => {
                if (!newStageName.trim()) return;
                setEditNames([...editNames, newStageName.trim()]);
                setNewStageName("");
              }}
            >
              Añadir etapa
            </button>
          </div>
          <div className="kanban-editor-save">
            <button
              type="submit"
              className="primary-button"
              disabled={savingStages}
            >
              {savingStages ? "Guardando…" : "Guardar pipeline"}
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={savingStages}
              onClick={() => setEditing(false)}
            >
              Cancelar
            </button>
          </div>
        </form>
      )}

      {!editing && board !== null && (
        <>
          <div
            className="kanban-board"
            role="list"
            aria-label="Tablero de etapas"
          >
            {columns.map((stage) => (
              <div
                key={stage.key}
                className={`kanban-column${dropTarget === stage.key ? " drop-target" : ""}`}
                role="listitem"
                onDragOver={(event) => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "move";
                  setDropTarget(stage.key);
                }}
                onDragLeave={() => {
                  setDropTarget((current) =>
                    current === stage.key ? null : current,
                  );
                }}
                onDrop={(event) => onDropOnStage(event, stage.key)}
              >
                <div className="kanban-column-head">
                  <strong>{stage.name}</strong>
                  <span className="counter">{stage.opportunities.length}</span>
                  <span
                    className="kanban-column-prob"
                    title="Probabilidad de cierre de la etapa"
                  >
                    {stage.probability}%
                  </span>
                </div>
                <div className="kanban-column-body">
                  {stage.opportunities.length === 0 && (
                    <div className="kanban-column-empty">Sin oportunidades</div>
                  )}
                  {stage.opportunities.map((card) => (
                    <Card
                      key={card.id}
                      card={card}
                      dragging={dragFrom?.id === card.id}
                      onDragStart={onDragStart}
                      onDragEnd={() => setDragFrom(null)}
                      onOpenDetail={setDetailLeadId}
                      onClose={openCloseModal}
                    />
                  ))}
                </div>
                {movingId && (
                  <div className="kanban-moving" role="status">
                    Moviendo…
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="kanban-queue">
            <div className="panel-heading">
              <div>
                <p>Cola</p>
                <h3>Leads sin asignar</h3>
              </div>
              <span className="counter">{unassigned.length}</span>
            </div>
            {unassigned.length === 0 && (
              <div className="empty-state">
                No hay leads sin asignar en la cola.
              </div>
            )}
            {unassigned.length > 0 && (
              <div className="table-wrap">
                <table>
                  <caption className="sr-only">
                    Leads sin comercial asignado
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Lead</th>
                      <th scope="col">Puntuación</th>
                      <th scope="col">Oportunidades</th>
                      <th scope="col">Asignar a</th>
                    </tr>
                  </thead>
                  <tbody>
                    {unassigned.map((lead) => (
                      <tr key={lead.id}>
                        <td>
                          {lead.first_name || "Sin nombre"}
                          {lead.company_name ? ` (${lead.company_name})` : ""}
                          <br />
                          <small>{lead.email}</small>
                        </td>
                        <td>
                          <span
                            className={`score-badge ${
                              lead.score >= 70
                                ? "score-high"
                                : lead.score >= 40
                                  ? "score-medium"
                                  : "score-low"
                            }`}
                            title={lead.score_signals
                              .map(
                                (signal) =>
                                  `${signal.kind}: +${signal.points} (${signal.detail})`,
                              )
                              .join("\n")}
                            aria-label={`Puntuación ${lead.score} sobre 100`}
                          >
                            {lead.score}
                          </span>
                        </td>
                        <td>
                          {lead.opportunities.length === 0
                            ? "—"
                            : lead.opportunities
                                .map(
                                  (opp) =>
                                    `${opp.name} · ${formatValue(opp.monetary_value, opp.currency)}`,
                                )
                                .join(" / ")}
                        </td>
                        <td className="queue-actions">
                          <select
                            aria-label={`Asignar lead ${lead.email}`}
                            value=""
                            disabled={assigningLead === lead.id}
                            onChange={(e) => {
                              if (e.target.value === "") return;
                              void assignLead(lead.id, e.target.value);
                              e.target.value = "";
                            }}
                          >
                            <option value="">Asignar a…</option>
                            {users.map((user) => (
                              <option key={user.id} value={user.id}>
                                {user.username} ({user.role})
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => setDetailLeadId(lead.id)}
                          >
                            Ficha
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {closingCard && (
        <form
          className="close-modal"
          onSubmit={(event) => void submitClose(event)}
          aria-label={`Cerrar ${closingCard.name}`}
        >
          <h4>Cerrar «{closingCard.name}»</h4>
          <p className="muted-text">
            {formatValue(closingCard.monetary_value, closingCard.currency)} ·
            cambio auditado
          </p>
          <label>
            Resultado
            <select
              value={closeOutcome}
              onChange={(e) =>
                setCloseOutcome(e.target.value as "won" | "lost")
              }
            >
              <option value="won">Ganada</option>
              <option value="lost">Perdida</option>
            </select>
          </label>
          {closeOutcome === "lost" && (
            <label>
              Motivo de pérdida
              <input
                list="lost-reasons"
                value={closeReason}
                maxLength={255}
                placeholder="Precio demasiado alto, presupuesto…"
                onChange={(e) => setCloseReason(e.target.value)}
              />
              <datalist id="lost-reasons">
                {LOST_REASONS.map((reason) => (
                  <option key={reason} value={reason} />
                ))}
              </datalist>
            </label>
          )}
          <label>
            Probabilidad de cierre (0-100, opcional)
            <input
              type="number"
              min={0}
              max={100}
              value={closeProbability}
              placeholder={closeOutcome === "won" ? "100" : "0"}
              onChange={(e) => setCloseProbability(e.target.value)}
            />
          </label>
          <div className="close-modal-actions">
            <button
              type="submit"
              className="primary-button"
              disabled={savingClose}
            >
              {savingClose ? "Cerrando…" : "Confirmar cierre"}
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={savingClose}
              onClick={() => setClosingCard(null)}
            >
              Cancelar
            </button>
          </div>
        </form>
      )}

      <LeadTimelineDrawer
        token={token}
        leadId={detailLeadId}
        onClose={() => setDetailLeadId(null)}
      />
    </section>
  );
}
