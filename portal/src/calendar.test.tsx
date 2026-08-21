import { expect, test } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CalendarSection, CalendarDay } from "./calendar";
import { ActivityRow } from "./activities";

type CapturedRequest = { path: string; method: string };

function requestPath(input: RequestInfo | URL): string {
  const url = new URL(String(input), "http://portal.test");
  return `${url.pathname}${url.search}`.replace(/^\/api\/bridge/, "");
}

function toLocalISO(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function addDays(date: Date, days: number): Date {
  const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  copy.setDate(copy.getDate() + days);
  return copy;
}

function activity(overrides: Partial<ActivityRow> = {}): ActivityRow {
  return {
    id: "act-1",
    lead_id: null,
    lead_email: null,
    lead_name: null,
    opportunity_id: null,
    opportunity_name: null,
    title: "Llamada urgente",
    kind: "call",
    description: null,
    due_at: "2026-08-10T09:00:00",
    remind_at: null,
    reminded_at: null,
    remind_email: null,
    status: "pending",
    assigned_to: null,
    assignee_username: null,
    completed_at: null,
    completed_by: null,
    created_at: "2026-08-01T08:00:00",
    ...overrides,
  };
}

function buildAgenda(startISO: string, endISO: string) {
  const start = new Date(`${startISO}T00:00:00`);
  const end = new Date(`${endISO}T00:00:00`);
  const event1 = toLocalISO(start); // pending + overdue
  const event2 = toLocalISO(addDays(start, 2)); // pending
  const event3 = toLocalISO(addDays(start, 4)); // done
  const days: CalendarDay[] = [];
  const totals = {
    total: 0,
    pending: 0,
    completed: 0,
    cancelled: 0,
    overdue: 0,
  };
  let cursor = new Date(start.getFullYear(), start.getMonth(), start.getDate());
  while (cursor <= end) {
    const iso = toLocalISO(cursor);
    let day: CalendarDay = {
      date: iso,
      total: 0,
      pending: 0,
      completed: 0,
      cancelled: 0,
      overdue: 0,
      activities: [],
    };
    if (iso === event1) {
      day = {
        ...day,
        total: 1,
        pending: 1,
        overdue: 1,
        activities: [
          activity({
            id: `act-${iso}`,
            title: "Llamada urgente",
            due_at: `${iso}T09:00:00`,
            status: "pending",
          }),
        ],
      };
    } else if (iso === event2) {
      day = {
        ...day,
        total: 1,
        pending: 1,
        activities: [
          activity({
            id: `act-${iso}`,
            title: "Reunión de cierre",
            kind: "meeting",
            due_at: `${iso}T11:00:00`,
          }),
        ],
      };
    } else if (iso === event3) {
      day = {
        ...day,
        total: 1,
        completed: 1,
        activities: [
          activity({
            id: `act-${iso}`,
            title: "Follow-up hecho",
            kind: "follow_up",
            due_at: `${iso}T10:00:00`,
            status: "done",
          }),
        ],
      };
    }
    totals.total += day.total;
    totals.pending += day.pending;
    totals.completed += day.completed;
    totals.overdue += day.overdue;
    days.push(day);
    cursor = addDays(cursor, 1);
  }
  return {
    range: { start: startISO, end: endISO },
    tz_offset: 0,
    days,
    totals,
  };
}

async function renderSection(captured: CapturedRequest[] = []) {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    captured.push({ path, method: init?.method ?? "GET" });
    const match = path.match(
      /calendar\/agenda\?.*start=(\d{4}-\d{2}-\d{2}).*end=(\d{4}-\d{2}-\d{2})/,
    );
    if (match) {
      return new Response(JSON.stringify(buildAgenda(match[1], match[2])), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ detail: "no encontrado" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  render(<CalendarSection token="token-test" refreshRevision={0} />);
}

test("muestra la rejilla del mes con badges y totales", async () => {
  await renderSection();
  await waitFor(() => {
    expect(screen.getByText("3 actividades")).toBeTruthy();
  });
  expect(screen.getByText("2 pendientes")).toBeTruthy();
  expect(screen.getByText("1 hechas")).toBeTruthy();
  expect(screen.getByText("1 vencidas")).toBeTruthy();
  // Badges en las celdas del mes.
  expect(screen.getByText("⚠ 1")).toBeTruthy();
  expect(screen.getAllByText("✓ 1").length).toBeGreaterThan(0);
  // Días de la semana como cabecera.
  for (const label of ["L", "M", "X", "J", "V", "S", "D"]) {
    expect(screen.getAllByText(label).length).toBeGreaterThan(0);
  }
});

test("la vista semana pide el rango de la semana y pinta sus columnas", async () => {
  const captured: CapturedRequest[] = [];
  await renderSection(captured);
  await userEvent.click(screen.getByRole("tab", { name: "Semana" }));
  await waitFor(() => {
    expect(captured.some((r) => r.path.includes("calendar/agenda"))).toBe(true);
  });
  // El último fetch es el de la semana: rango de 7 días.
  const last = captured[captured.length - 1];
  const start = last.path.match(/start=(\d{4}-\d{2}-\d{2})/)?.[1];
  const end = last.path.match(/end=(\d{4}-\d{2}-\d{2})/)?.[1];
  expect(start && end).toBeTruthy();
  const days =
    (new Date(`${end}T00:00:00`).getTime() -
      new Date(`${start}T00:00:00`).getTime()) /
      86_400_000 +
    1;
  expect(days).toBe(7);
  await waitFor(() => {
    expect(screen.getByText("Llamada urgente")).toBeTruthy();
  });
  expect(document.querySelectorAll(".calendar-week-col").length).toBe(7);
});

test("la vista día muestra la lista completa del día", async () => {
  await renderSection();
  await userEvent.click(screen.getByRole("tab", { name: "Día" }));
  await waitFor(() => {
    expect(screen.getByText("Llamada urgente")).toBeTruthy();
  });
  expect(screen.getByText("Pendiente")).toBeTruthy();
});

test("clic en una celda con eventos abre la vista día", async () => {
  await renderSection();
  await waitFor(() => {
    expect(screen.getByText("⚠ 1")).toBeTruthy();
  });
  const cell = screen
    .getAllByRole("button")
    .find((b) => b.textContent?.includes("⚠ 1"));
  expect(cell).toBeTruthy();
  await userEvent.click(cell!);
  await waitFor(() => {
    expect(screen.getByText("Llamada urgente")).toBeTruthy();
  });
});

test("la navegación prev/next cambia el periodo y vuelve a pedir datos", async () => {
  const captured: CapturedRequest[] = [];
  await renderSection(captured);
  await waitFor(() => {
    expect(captured.length).toBeGreaterThan(0);
  });
  const before = captured[captured.length - 1].path;
  await userEvent.click(screen.getByRole("button", { name: "▶" }));
  await waitFor(() => {
    expect(captured[captured.length - 1].path).not.toBe(before);
  });
});
