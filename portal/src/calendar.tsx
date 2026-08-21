import { useEffect, useMemo, useState } from "react";
import { apiRequest } from "./api";
import { ActivityRow, KIND_LABELS, STATUS_LABELS } from "./activities";

export type CalendarDay = {
  date: string; // YYYY-MM-DD (día local)
  total: number;
  pending: number;
  completed: number;
  cancelled: number;
  overdue: number;
  activities: ActivityRow[];
};

type AgendaResponse = {
  range: { start: string; end: string };
  tz_offset: number;
  days: CalendarDay[];
  totals: {
    total: number;
    pending: number;
    completed: number;
    cancelled: number;
    overdue: number;
  };
};

const WEEKDAY_LABELS = ["L", "M", "X", "J", "V", "S", "D"];
const MONTH_NAMES = [
  "enero",
  "febrero",
  "marzo",
  "abril",
  "mayo",
  "junio",
  "julio",
  "agosto",
  "septiembre",
  "octubre",
  "noviembre",
  "diciembre",
];

function toLocalISO(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function startOfWeek(date: Date): Date {
  const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dow = (copy.getDay() + 6) % 7; // lunes = 0
  copy.setDate(copy.getDate() - dow);
  return copy;
}

function addDays(date: Date, days: number): Date {
  const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  copy.setDate(copy.getDate() + days);
  return copy;
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("es-ES", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDayShort(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("es-ES", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

export function CalendarSection({
  token,
  refreshRevision,
}: {
  token: string;
  refreshRevision: number;
}) {
  const [view, setView] = useState<"month" | "week" | "day">("month");
  const [anchor, setAnchor] = useState<Date>(() => new Date());
  const [agenda, setAgenda] = useState<AgendaResponse | null>(null);
  const [error, setError] = useState("");

  const tzOffset = -new Date().getTimezoneOffset();

  const range = useMemo(() => {
    if (view === "week") {
      const mon = startOfWeek(anchor);
      return { start: toLocalISO(mon), end: toLocalISO(addDays(mon, 6)) };
    }
    if (view === "day") {
      const day = toLocalISO(anchor);
      return { start: day, end: day };
    }
    const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
    const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
    return { start: toLocalISO(first), end: toLocalISO(last) };
  }, [view, anchor]);

  const periodLabel = useMemo(() => {
    if (view === "day") {
      return anchor.toLocaleDateString("es-ES", {
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric",
      });
    }
    if (view === "week") {
      const mon = startOfWeek(anchor);
      const sun = addDays(mon, 6);
      const sameMonth = mon.getMonth() === sun.getMonth();
      const fmt = (d: Date) =>
        d.toLocaleDateString("es-ES", { day: "numeric", month: "short" });
      return sameMonth
        ? `${fmt(mon)} – ${fmt(sun)} ${mon.getFullYear()}`
        : `${fmt(mon)} ${mon.getFullYear()} – ${fmt(sun)} ${sun.getFullYear()}`;
    }
    const monthName = MONTH_NAMES[anchor.getMonth()];
    return `${monthName.charAt(0).toUpperCase()}${monthName.slice(1)} de ${anchor.getFullYear()}`;
  }, [view, anchor]);

  useEffect(() => {
    let cancelled = false;
    setError("");
    setAgenda(null);
    const params = new URLSearchParams({
      start: range.start,
      end: range.end,
      tz_offset: String(tzOffset),
    });
    apiRequest<AgendaResponse>(`/calendar/agenda?${params.toString()}`, {
      token,
    })
      .then((data) => {
        if (!cancelled) setAgenda(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Error cargando el calendario",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [range.start, range.end, tzOffset, token, refreshRevision]);

  const daysByDate = useMemo(() => {
    const map = new Map<string, CalendarDay>();
    for (const day of agenda?.days ?? []) map.set(day.date, day);
    return map;
  }, [agenda]);

  function shift(delta: number) {
    if (view === "month") {
      setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + delta, 1));
    } else if (view === "week") {
      setAnchor(addDays(startOfWeek(anchor), delta * 7));
    } else {
      setAnchor(addDays(anchor, delta));
    }
  }

  const grid = useMemo(() => {
    if (view !== "month") return [];
    const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
    const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
    const start = startOfWeek(first);
    const cells: Date[] = [];
    let cursor = start;
    while (cursor <= last || cells.length % 7 !== 0) {
      cells.push(cursor);
      cursor = addDays(cursor, 1);
    }
    return cells;
  }, [view, anchor]);

  const totals = agenda?.totals;

  return (
    <section className="calendar-section" aria-label="Calendario de comercial">
      <div className="calendar-toolbar">
        <div className="segmented" role="tablist" aria-label="Vista del calendario">
          <button
            type="button"
            role="tab"
            aria-selected={view === "month"}
            className={view === "month" ? "active" : ""}
            onClick={() => setView("month")}
          >
            Mes
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "week"}
            className={view === "week" ? "active" : ""}
            onClick={() => setView("week")}
          >
            Semana
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "day"}
            className={view === "day" ? "active" : ""}
            onClick={() => setView("day")}
          >
            Día
          </button>
        </div>
        <div className="calendar-nav">
          <button type="button" className="ghost-button" onClick={() => shift(-1)}>
            ◀
          </button>
          <button
            type="button"
            className="ghost-button"
            onClick={() => setAnchor(new Date())}
          >
            Hoy
          </button>
          <button type="button" className="ghost-button" onClick={() => shift(1)}>
            ▶
          </button>
        </div>
        <h4 className="calendar-period">{periodLabel}</h4>
        {totals && (
          <div className="calendar-totals">
            <span className="pill pill-neutral">{totals.total} actividades</span>
            <span className="pill pill-blue">{totals.pending} pendientes</span>
            <span className="pill pill-green">{totals.completed} hechas</span>
            {totals.overdue > 0 && (
              <span className="pill pill-red">{totals.overdue} vencidas</span>
            )}
          </div>
        )}
      </div>

      {error && <p className="error-text">{error}</p>}
      {!agenda && !error && (
        <p className="muted-text">Cargando calendario…</p>
      )}

      {view === "month" && agenda && (
        <div className="calendar-month-grid">
          {WEEKDAY_LABELS.map((label) => (
            <div key={label} className="calendar-weekday">
              {label}
            </div>
          ))}
          {grid.map((date) => {
            const iso = toLocalISO(date);
            const day = daysByDate.get(iso);
            const inMonth = date.getMonth() === anchor.getMonth();
            return (
              <button
                key={iso}
                type="button"
                className={`calendar-cell${inMonth ? "" : " out-month"}${
                  day && day.total > 0 ? " has-events" : ""
                }`}
                onClick={() => {
                  setAnchor(date);
                  setView("day");
                }}
              >
                <span className="calendar-cell-day">{date.getDate()}</span>
                {day && day.total > 0 && (
                  <span className="calendar-cell-badges">
                    {day.overdue > 0 && (
                      <span className="badge badge-red">⚠ {day.overdue}</span>
                    )}
                    {day.pending > 0 && (
                      <span className="badge badge-blue">{day.pending}</span>
                    )}
                    {day.completed > 0 && (
                      <span className="badge badge-green">✓ {day.completed}</span>
                    )}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {view === "week" && agenda && (
        <div className="calendar-week-grid">
          {daysByDate.size === 0 && (
            <p className="muted-text">Sin actividades en esta semana.</p>
          )}
          {agenda.days.map((day) => (
            <div key={day.date} className="calendar-week-col">
              <button
                type="button"
                className="calendar-week-head"
                onClick={() => {
                  setAnchor(new Date(`${day.date}T00:00:00`));
                  setView("day");
                }}
              >
                {fmtDayShort(day.date)}
              </button>
              {day.activities.length === 0 && (
                <span className="muted-text">—</span>
              )}
              {day.activities.map((activity) => (
                <div
                  key={activity.id}
                  className={`calendar-week-item${activity.status === "done" ? " done" : ""}`}
                >
                  <span className="calendar-item-time">
                    {fmtTime(activity.due_at)}
                  </span>
                  <span className="calendar-item-title">{activity.title}</span>
                  <span className="muted-text">
                    {KIND_LABELS[activity.kind] ?? activity.kind}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {view === "day" && agenda && (
        <div className="calendar-day-list">
          {agenda.days[0]?.activities.length === 0 && (
            <p className="muted-text">Sin actividades este día.</p>
          )}
          {agenda.days[0]?.activities.map((activity) => (
            <div
              key={activity.id}
              className={`calendar-day-item${activity.status === "done" ? " done" : ""}`}
            >
              <div className="calendar-day-main">
                <span className="calendar-item-time">
                  {fmtTime(activity.due_at)}
                </span>
                <strong>{activity.title}</strong>
                <span className="muted-text">
                  {KIND_LABELS[activity.kind] ?? activity.kind}
                </span>
                {activity.lead_name && (
                  <span className="muted-text"> · {activity.lead_name}</span>
                )}
                {activity.assignee_username && (
                  <span className="muted-text"> · {activity.assignee_username}</span>
                )}
              </div>
              <span
                className={`status-pill status-${activity.status}`}
              >
                {STATUS_LABELS[activity.status] ?? activity.status}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
