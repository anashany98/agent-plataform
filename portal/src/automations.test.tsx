import { expect, test } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AutomationsSection } from "./sections/Automations";

type CapturedRequest = {
  path: string;
  method: string;
  body?: unknown;
};

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

function statusFixture(overrides: Record<string, unknown> = {}) {
  return {
    engine: {
      quote_expiry: {
        last_run_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
        last_status: "success",
        last_summary: "Presupuesto quote-1 (queued_for_manual_delivery)",
      },
      dunning: {
        last_run_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
        last_status: "success",
        last_summary: "Factura INV-2026-0001, paso 2 (enviado)",
      },
      low_stock: {
        last_run_at: new Date(Date.now() - 3600_000).toISOString(),
        last_status: "success",
        last_summary:
          "3 producto(s) avisado(s), 2 correo(s) enviado(s), 0 fallo(s)",
      },
      cart_abandonment: null,
    },
    queue: { pending: 1, dead: 0 },
    scheduled_tasks: { active: 2, paused: 0 },
    dead_letter: [],
    ...overrides,
  };
}

const DEAD_LETTER_FIXTURE = {
  dead_letter: [
    {
      id: "msg-dead-1",
      topic: "campaign.deliver",
      topic_label: "Envío de una campaña a un destinatario",
      created_at: new Date(Date.now() - 3600_000).toISOString(),
      attempt_count: 3,
      max_attempts: 3,
      permanent: false,
      reason:
        "Se intentó varias veces y no se pudo. El proveedor no respondió (problema temporal de conexión).",
    },
    {
      id: "msg-dead-2",
      topic: "ghl.lead_capture",
      topic_label: "Captura de oportunidad en GoHighLevel",
      created_at: null,
      attempt_count: 1,
      max_attempts: 3,
      permanent: true,
      reason:
        "No se pudo completar y no se reintentará automáticamente. La integración (GoHighLevel) no está configurada: revisa las credenciales en Ajustes.",
    },
  ],
};

async function renderSection(
  captured: CapturedRequest[] = [],
  canWrite = true,
) {
  const refreshRevision = 0;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    captured.push({ path, method });
    if (method === "GET" && path === "/automations/status") {
      return response(statusFixture({ ...DEAD_LETTER_FIXTURE }));
    }
    if (method === "POST" && /^\/outbox\/[^/]+\/retry$/.test(path)) {
      return response({ status: "requeued" });
    }
    if (method === "POST" && path === "/automations/sweep") {
      return response({
        quote_expiry: { reminded: 2, failed: 0 },
        dunning: { delivered: 1, failed: 0 },
      });
    }
    return response({ detail: "not found" }, 404);
  }) as typeof fetch;
  render(
    <AutomationsSection
      token="t"
      canWrite={canWrite}
      refreshRevision={refreshRevision}
    />,
  );
  void refreshRevision;
}

test("muestra la última actividad de cada automatización en lenguaje llano", async () => {
  await renderSection();
  expect(await screen.findByText("Recordatorios de presupuesto")).toBeTruthy();
  expect(screen.getByText("Avisos de cobro vencido")).toBeTruthy();
  expect(screen.getByText("Alerta de stock bajo")).toBeTruthy();
  expect(screen.getByText("Carritos olvidados")).toBeTruthy();
  await waitFor(() => {
    expect(
      screen.getByText(
        /3 producto\(s\) avisado\(s\), 2 correo\(s\) enviado\(s\)/,
      ),
    ).toBeTruthy();
  });
  expect(screen.getByText(/Todavía no se ha ejecutado/)).toBeTruthy();
  const summary = screen.getByText(/Tareas programadas:/);
  const summaryBlock = summary.closest("p");
  expect(summaryBlock?.textContent).toContain(
    "1 en cola de reintento, 0 fallados definitivamente",
  );
});

test("permite ejecutar ahora y muestra el resultado en lenguaje llano", async () => {
  const captured: CapturedRequest[] = [];
  await renderSection(captured);
  const button = await screen.findByRole("button", { name: /Ejecutar ahora/ });
  await userEvent.click(button);
  expect(
    captured.some(
      (r) => r.method === "POST" && r.path === "/automations/sweep",
    ),
  ).toBe(true);
  expect(
    await screen.findByText("Ejecutado: 3 aviso(s) enviado(s), 0 error(es)."),
  ).toBeTruthy();
});

test("muestra la cola de reintentos con el motivo en lenguaje llano", async () => {
  await renderSection();
  expect(
    await screen.findByRole("heading", { name: "Envíos que fallaron" }),
  ).toBeTruthy();
  expect(
    screen.getByText("Envío de una campaña a un destinatario"),
  ).toBeTruthy();
  expect(screen.getByText(/problema temporal de conexión/)).toBeTruthy();
  expect(
    screen.getByText("Captura de oportunidad en GoHighLevel"),
  ).toBeTruthy();
  expect(
    screen.getByText(/no está configurada: revisa las credenciales/),
  ).toBeTruthy();
  expect(screen.getByText(/Se intentó 3 de 3 veces/)).toBeTruthy();
});

test("el botón Reintentar reencola el mensaje y refresca el panel", async () => {
  const captured: CapturedRequest[] = [];
  await renderSection(captured);
  const retry = (
    await screen.findAllByRole("button", { name: "Reintentar" })
  )[0];
  await userEvent.click(retry);
  await waitFor(() => {
    expect(
      captured.some(
        (r) => r.method === "POST" && r.path === "/outbox/msg-dead-1/retry",
      ),
    ).toBe(true);
  });
  expect(
    await screen.findByText("Reencolado: se reintentará automáticamente."),
  ).toBeTruthy();
});

test("oculta la cola de reintentos a quien no puede operar", async () => {
  await renderSection([], false);
  await screen.findByText("Recordatorios de presupuesto");
  expect(
    screen.queryByRole("heading", { name: "Envíos que fallaron" }),
  ).toBeNull();
  expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
});
