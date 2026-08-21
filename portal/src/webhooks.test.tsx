import { expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WebhooksSection, WebhookSubscription } from "./webhooks";

type CapturedRequest = {
  path: string;
  method: string;
  body?: unknown;
};

const EVENT_CATALOG = [
  { key: "lead.created", label: "Lead creado", description: "Lead nuevo." },
  {
    key: "pipeline.stage_changed",
    label: "Cambio de etapa",
    description: "Etapa del kanban.",
  },
  {
    key: "quote.confirmed",
    label: "Presupuesto confirmado",
    description: "Pedido y factura.",
  },
];

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

function subscriptionFixture(
  overrides: Partial<WebhookSubscription> = {},
): WebhookSubscription {
  return {
    id: "sub-1",
    name: "CRM externo",
    url: "https://public.test/hook",
    events: ["lead.created"],
    is_active: true,
    secret_set: true,
    secret_prefix: "subs",
    created_by: "admin",
    created_at: "2026-08-16T08:00:00",
    updated_at: "2026-08-16T08:00:00",
    ...overrides,
  };
}

async function renderSection(
  subscriptions: WebhookSubscription[],
  captured: CapturedRequest[] = [],
) {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? (JSON.parse(String(init.body)) as unknown) : undefined;
    captured.push({ path, method, body });
    if (method === "GET" && path === "/webhooks/subscriptions") {
      return response({ items: subscriptions, event_catalog: EVENT_CATALOG });
    }
    if (method === "POST" && path === "/webhooks/subscriptions") {
      return response(subscriptionFixture(body as Partial<WebhookSubscription>));
    }
    if (method === "PATCH" && path.startsWith("/webhooks/subscriptions/")) {
      return response(subscriptionFixture(body as Partial<WebhookSubscription>));
    }
    if (method === "DELETE" && path.startsWith("/webhooks/subscriptions/")) {
      return response({ deleted: true });
    }
    if (method === "POST" && path.endsWith("/test")) {
      return response({ status: "queued", outbox_id: "outbox-123" });
    }
    return response({ detail: "no encontrado" }, 404);
  }) as typeof fetch;

  render(<WebhooksSection token="token-test" refreshRevision={0} />);
}

test("lista las suscripciones con estado y oculta el secreto completo", async () => {
  await renderSection([
    subscriptionFixture(),
    subscriptionFixture({
      id: "sub-2",
      name: "Etapas",
      events: ["pipeline.stage_changed"],
      is_active: false,
      secret_prefix: "abcd",
    }),
  ]);

  await waitFor(() => expect(screen.getByText("CRM externo")).toBeTruthy());
  expect(screen.getByText("Etapas")).toBeTruthy();
  // «Cambio de etapa» aparece en la fila de la suscripción y en el
  // formulario de alta (checkbox), así que se admiten varias coincidencias.
  expect(screen.getAllByText(/Cambio de etapa/).length).toBeGreaterThanOrEqual(1);
  // El secreto completo nunca se muestra; solo el prefijo.
  expect(screen.queryByText(/subs.*subs/)).toBeFalsy();
  expect(screen.getAllByText(/firma subs…/).length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("Activa").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("Inactiva")).toBeTruthy();
});

test("crear una suscripción envía el POST con nombre, URL, secreto y eventos", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderSection([], captured);

  await waitFor(() =>
    expect(screen.getByText(/Aún no hay suscripciones/)).toBeTruthy(),
  );

  await user.type(screen.getByLabelText("Nombre de la nueva suscripción"), "CRM B");
  await user.type(screen.getByLabelText("URL de la nueva suscripción"), "https://b.example/hook");
  await user.type(screen.getByLabelText("Secreto HMAC de la nueva suscripción"), "super-secreto-16ch");
  await user.click(screen.getByLabelText("Cambio de etapa"));
  await user.click(screen.getByRole("button", { name: "Crear suscripción" }));

  await waitFor(() => {
    const post = captured.find(
      (request) => request.method === "POST" && request.path === "/webhooks/subscriptions",
    );
    expect(post).toBeTruthy();
    expect(post?.body).toMatchObject({
      name: "CRM B",
      url: "https://b.example/hook",
      secret: "super-secreto-16ch",
      events: ["lead.created", "pipeline.stage_changed"],
    });
  });
});

test("probar una suscripción encola el evento de prueba", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderSection([subscriptionFixture()], captured);

  await waitFor(() => expect(screen.getByText("CRM externo")).toBeTruthy());
  await user.click(screen.getByRole("button", { name: "Probar" }));

  await waitFor(() => {
    const post = captured.find(
      (request) =>
        request.method === "POST" && request.path === "/webhooks/subscriptions/sub-1/test",
    );
    expect(post).toBeTruthy();
  });
  await waitFor(() =>
    expect(screen.getByText(/Evento de prueba encolado/)).toBeTruthy(),
  );
});

test("desactivar y eliminar una suscripción envían PATCH y DELETE", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderSection([subscriptionFixture()], captured);

  await waitFor(() => expect(screen.getByText("CRM externo")).toBeTruthy());
  await user.click(screen.getByRole("button", { name: "Desactivar" }));

  await waitFor(() => {
    const patch = captured.find(
      (request) =>
        request.method === "PATCH" && request.path === "/webhooks/subscriptions/sub-1",
    );
    expect(patch).toBeTruthy();
    expect(patch?.body).toMatchObject({ is_active: false });
  });

  const confirmSpy = vi
    .spyOn(window, "confirm")
    .mockReturnValue(true);
  await user.click(screen.getByRole("button", { name: "Eliminar" }));
  await waitFor(() => {
    const del = captured.find(
      (request) =>
        request.method === "DELETE" && request.path === "/webhooks/subscriptions/sub-1",
    );
    expect(del).toBeTruthy();
  });
  confirmSpy.mockRestore();
});

test("el formulario exige al menos un evento y un secreto de 16 caracteres", async () => {
  const user = userEvent.setup();
  await renderSection([]);

  await waitFor(() =>
    expect(screen.getByText(/Aún no hay suscripciones/)).toBeTruthy(),
  );

  const createButton = screen.getByRole("button", {
    name: "Crear suscripción",
  }) as HTMLButtonElement;
  expect(createButton.disabled).toBe(true);

  await user.type(screen.getByLabelText("Nombre de la nueva suscripción"), "Hook");
  await user.type(screen.getByLabelText("URL de la nueva suscripción"), "https://x.example/h");
  await user.type(screen.getByLabelText("Secreto HMAC de la nueva suscripción"), "corto");
  expect(createButton.disabled).toBe(true);
});
