import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TodaySection } from "./today";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestPath(input: RequestInfo | URL): string {
  const url = new URL(String(input), "http://portal.test");
  return `${url.pathname}${url.search}`.replace(/^\/api\/bridge/, "");
}

function todayPayload(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    cards: {
      pending_approvals: { count: 2, items: [] },
      campaigns_pending_retry: {
        count: 1,
        items: [{ label: "Oferta septiembre" }],
      },
      low_stock: { count: 3, items: [{ label: "BIC negro · 3 uds" }] },
      urgent_messages: {
        count: 1,
        items: [{ label: "Cliente urgente: necesito respuesta ya" }],
      },
      engine_failures: {
        count: 1,
        items: [{ label: "Envío de una campaña a un destinatario" }],
      },
      ...overrides,
    },
  };
}

const FULL_PERMISSIONS = {
  approve: true,
  manage_leads: true,
  manage_users: true,
  view_costs: true,
  import_catalog: true,
};

async function renderToday(payload: unknown = todayPayload()) {
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    if (requestPath(input) === "/today") {
      return response(payload);
    }
    return response({ detail: "Ruta no mockeada" }, 500);
  }) as typeof fetch;
  render(<TodaySection token="token" permissions={FULL_PERMISSIONS} />);
}

test("la pantalla Hoy muestra las cinco tarjetas con sus conteos", async () => {
  await renderToday();
  expect(await screen.findByText("Aprobar propuestas")).toBeTruthy();
  expect(screen.getByText("Reenviar campañas")).toBeTruthy();
  expect(screen.getByText("Mensajes urgentes")).toBeTruthy();
  expect(screen.getByText("Stock bajo")).toBeTruthy();
  expect(screen.getByText("Envíos fallados")).toBeTruthy();
  // Conteos como insignia (dos tarjetas con 1: campañas y mensajes).
  expect(screen.getByText("2")).toBeTruthy();
  expect(screen.getAllByText("1").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("3")).toBeTruthy();
  // Muestra de las tarjetas pendientes.
  expect(screen.getByText("Oferta septiembre")).toBeTruthy();
  expect(screen.getByText("BIC negro · 3 uds")).toBeTruthy();
  expect(screen.getByText("Ir a aprobaciones")).toBeTruthy();
  expect(screen.getByText("Revisar campañas")).toBeTruthy();
  expect(
    screen.getByText("Envío de una campaña a un destinatario"),
  ).toBeTruthy();
  expect(screen.getByText("Ir a Automatizaciones")).toBeTruthy();
});

test("con todo en cero muestra «Todo en orden» sin CTA", async () => {
  await renderToday(
    todayPayload({
      pending_approvals: { count: 0, items: [] },
      campaigns_pending_retry: { count: 0, items: [] },
      low_stock: { count: 0, items: [] },
      urgent_messages: { count: 0, items: [] },
      engine_failures: { count: 0, items: [] },
    }),
  );
  expect((await screen.findAllByText("Todo en orden")).length).toBe(5);
  expect(screen.queryByText("Ir a aprobaciones")).toBeNull();
  expect(screen.queryByText("Revisar campañas")).toBeNull();
});

test("las tarjetas navegan a su sección con un clic", async () => {
  window.location.hash = "";
  sessionStorage.clear();
  await renderToday();

  await userEvent.click(
    await screen.findByRole("button", { name: /Ir a aprobaciones/ }),
  );
  expect(window.location.hash).toBe("#aprobaciones");

  await userEvent.click(screen.getByRole("button", { name: /Revisar campañas/ }));
  expect(sessionStorage.getItem("portal_clientes_tab")).toBe("campanas");
  expect(window.location.hash).toBe("#clientes");

  await userEvent.click(screen.getByRole("button", { name: /Ver bandeja/ }));
  expect(sessionStorage.getItem("portal_clientes_tab")).toBe("social");
  expect(window.location.hash).toBe("#clientes");

  await userEvent.click(screen.getByRole("button", { name: /Ver productos/ }));
  expect(window.location.hash).toBe("#catalogo");

  await userEvent.click(
    screen.getByRole("button", { name: /Ir a Automatizaciones/ }),
  );
  expect(window.location.hash).toBe("#automatizaciones");
});

test("el RBAC oculta las tarjetas que el rol no puede alcanzar", async () => {
  const restricted = { ...FULL_PERMISSIONS, approve: false, manage_leads: false };
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    if (requestPath(input) === "/today") return response(todayPayload());
    return response({ detail: "Ruta no mockeada" }, 500);
  }) as typeof fetch;
  render(<TodaySection token="token" permissions={restricted} />);

  await screen.findByText("Stock bajo");
  // El fallo del motor no depende de permisos: es parte de «qué necesita tu
  // atención» y enlaza al panel de Automatizaciones, visible para todos.
  expect(screen.getByText("Envíos fallados")).toBeTruthy();
  expect(screen.queryByText("Aprobar propuestas")).toBeNull();
  expect(screen.queryByText("Reenviar campañas")).toBeNull();
  expect(screen.queryByText("Mensajes urgentes")).toBeNull();
});

test("un error del endpoint se muestra como alerta", async () => {
  globalThis.fetch = (async () => response({ detail: "boom" }, 500)) as typeof fetch;
  render(<TodaySection token="token" permissions={FULL_PERMISSIONS} />);
  expect(await screen.findByRole("alert")).toBeTruthy();
});
