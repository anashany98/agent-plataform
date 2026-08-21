import { expect, test } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { ActivitiesSection, ActivityRow } from "./activities";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function activityFixture(overrides: Partial<ActivityRow> = {}): ActivityRow {
  return {
    id: "act-1",
    lead_id: "lead-1",
    lead_email: "cliente@acme.test",
    lead_name: "Ana García",
    opportunity_id: null,
    opportunity_name: null,
    title: "Llamar a Acme",
    kind: "call",
    description: null,
    due_at: "2026-08-20T10:00:00Z",
    remind_at: "2026-08-19T09:00:00Z",
    reminded_at: null,
    remind_email: "cliente@acme.test",
    status: "pending",
    assigned_to: "user-1",
    assignee_username: "comercial",
    completed_at: null,
    completed_by: null,
    created_at: "2026-08-18T10:00:00Z",
    ...overrides,
  };
}

function setupFetch(overrides: {
  activities?: ActivityRow[];
  createStatus?: number;
  remindBody?: { delivery_status: string; provider: string };
} = {}) {
  const calls: Array<{ method: string; path: string }> = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://portal.test");
    const path = url.pathname.replace(/^\/api\/bridge/, "");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path });
    if (method === "GET" && path === "/activities") {
      return response(overrides.activities ?? [activityFixture()]);
    }
    if (method === "GET" && path === "/leads") {
      return response([
        {
          id: "lead-1",
          email: "cliente@acme.test",
          first_name: "Ana",
          company_name: "Acme S.L.",
        },
      ]);
    }
    if (method === "GET" && path === "/users") {
      return response([
        { id: "user-1", username: "comercial", role: "comercial" },
      ]);
    }
    if (method === "POST" && path === "/activities") {
      if (overrides.createStatus) return response({}, overrides.createStatus);
      return response(activityFixture({ id: "act-2", title: "Nueva tarea" }), 201);
    }
    if (method === "POST" && /^\/activities\/[^/]+\/remind$/.test(path)) {
      return response(
        overrides.remindBody ?? {
          delivery_status: "queued_for_manual_delivery",
          provider: "local_spool",
        },
      );
    }
    if (method === "PATCH" && /^\/activities\/[^/]+$/.test(path)) {
      return response(activityFixture({ status: "done", completed_at: "2026-08-18T12:00:00Z" }));
    }
    return response({}, 404);
  }) as typeof fetch;
  return calls;
}

async function renderActivities() {
  render(<ActivitiesSection token="token-test" refreshRevision={1} />);
  await screen.findByRole("heading", { name: "Tareas y recordatorios" });
}

test("muestra las tareas pendientes con su recordatorio y acciones", async () => {
  setupFetch();
  await renderActivities();
  expect(screen.getByText("Llamar a Acme")).toBeTruthy();
  expect(screen.getByText("Ana García")).toBeTruthy();
  expect(screen.getAllByText("Llamada").length).toBeGreaterThan(0);
  expect(screen.getByText("Pendiente")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Recordar ahora" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Completar" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Cancelar" })).toBeTruthy();
});

test("crear una tarea dispara el POST y recarga la lista", async () => {
  const calls = setupFetch();
  await renderActivities();
  const title = screen.getByLabelText("Título");
  fireEvent.change(title, { target: { value: "Nueva tarea" } });
  fireEvent.click(screen.getByRole("button", { name: "Crear tarea" }));
  await waitFor(() => {
    expect(
      calls.some(
        (call) => call.method === "POST" && call.path === "/activities",
      ),
    ).toBe(true);
  });
  expect(await screen.findByText("Tarea creada. Cambio auditado.")).toBeTruthy();
});

test("completar una tarea dispara el PATCH de estado", async () => {
  const calls = setupFetch();
  await renderActivities();
  fireEvent.click(screen.getByRole("button", { name: "Completar" }));
  await waitFor(() => {
    expect(
      calls.some(
        (call) =>
          call.method === "PATCH" && call.path === "/activities/act-1",
      ),
    ).toBe(true);
  });
  expect(await screen.findByText(/«Llamar a Acme» completada/)).toBeTruthy();
});

test("recordar ahora envía el recordatorio por el spool y lo confirma", async () => {
  setupFetch({
    remindBody: {
      delivery_status: "queued_for_manual_delivery",
      provider: "local_spool",
    },
  });
  await renderActivities();
  fireEvent.click(screen.getByRole("button", { name: "Recordar ahora" }));
  expect(
    await screen.findByText(
      /Recordatorio de «Llamar a Acme» en cola de entrega \(local_spool\)/,
    ),
  ).toBeTruthy();
});

test("muestra el error si la API falla al cargar", async () => {
  globalThis.fetch = (async () =>
    response({ detail: "El servicio no está disponible temporalmente." }, 503)) as typeof fetch;
  render(<ActivitiesSection token="token-test" refreshRevision={1} />);
  await waitFor(() => {
    expect(
      screen.getByText("El servicio no está disponible temporalmente."),
    ).toBeTruthy();
  });
});
