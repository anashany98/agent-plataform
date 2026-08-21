import { expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EmailSection, EmailTemplate } from "./email";

type CapturedRequest = {
  path: string;
  method: string;
  body?: unknown;
};

const VARIABLES = [
  { key: "store_name", label: "Nombre de la tienda", description: "Tienda." },
  { key: "lead.first_name", label: "Nombre del lead", description: "Lead." },
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

function templateFixture(
  overrides: Partial<EmailTemplate> = {},
): EmailTemplate {
  return {
    id: "tpl-1",
    name: "Seguimiento de presupuesto",
    subject: "Tu presupuesto {{quote.id}}",
    body: "Hola {{lead.first_name}}, mira tu presupuesto.",
    signature: null,
    is_active: true,
    created_by: "admin",
    created_at: "2026-08-16T08:00:00",
    updated_at: "2026-08-16T08:00:00",
    ...overrides,
  };
}

async function renderSection(
  templates: EmailTemplate[],
  captured: CapturedRequest[] = [],
  events: unknown[] = [],
) {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? (JSON.parse(String(init.body)) as unknown) : undefined;
    captured.push({ path, method, body });
    if (method === "GET" && path === "/email/templates") {
      return response({ items: templates, variables: VARIABLES });
    }
    if (method === "GET" && path === "/email/settings") {
      return response({ signature: "Equipo", tracking_enabled: true });
    }
    if (method === "GET" && path === "/email/tracking/events") {
      return response({ items: events });
    }
    if (method === "POST" && path === "/email/templates") {
      return response(templateFixture(body as Partial<EmailTemplate>));
    }
    if (method === "PATCH" && path.startsWith("/email/templates/")) {
      return response(templateFixture(body as Partial<EmailTemplate>));
    }
    if (method === "DELETE" && path.startsWith("/email/templates/")) {
      return response({ deleted: true });
    }
    if (method === "POST" && path.endsWith("/send-test")) {
      return response({
        provider: "local_spool",
        accepted: false,
        delivery_status: "queued_for_manual_delivery",
        tracking_token: "tk-abc123",
      });
    }
    if (method === "PUT" && path === "/email/settings") {
      return response({
        signature: "Equipo",
        tracking_enabled: true,
        updated_at: null,
      });
    }
    return response({ detail: "no encontrado" }, 404);
  }) as typeof fetch;

  render(<EmailSection token="token-test" refreshRevision={0} />);
}

test("lista plantillas con variables y eventos de tracking", async () => {
  await renderSection(
    [templateFixture()],
    [],
    [
      {
        id: "ev-1",
        token: "tk-abc123",
        event_type: "open",
        url: null,
        to: "cliente@example.invalid",
        template_name: "Seguimiento de presupuesto",
        created_at: "2026-08-16T10:00:00",
      },
    ],
  );

  await waitFor(() =>
    expect(screen.getAllByText("Seguimiento de presupuesto").length).toBeGreaterThanOrEqual(1),
  );
  expect(screen.getByText(/Tu presupuesto/)).toBeTruthy();
  // Variables del catálogo en el formulario.
  expect(screen.getAllByText("{{store_name}}").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("Apertura")).toBeTruthy();
  expect(screen.getByText("cliente@example.invalid")).toBeTruthy();
});

test("crear una plantilla envía el POST con nombre, asunto y cuerpo", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderSection([], captured);

  await waitFor(() =>
    expect(screen.getByText(/Aún no hay plantillas/)).toBeTruthy(),
  );

  await user.type(
    screen.getByLabelText("Nombre de la nueva plantilla"),
    "Bienvenida",
  );
  await user.type(
    screen.getByLabelText("Asunto de la nueva plantilla"),
    "Hola cliente",
  );
  await user.type(
    screen.getByLabelText("Cuerpo de la nueva plantilla"),
    "Bienvenido a la tienda",
  );
  await user.click(screen.getByRole("button", { name: "Crear plantilla" }));

  await waitFor(() => {
    const post = captured.find(
      (request) => request.method === "POST" && request.path === "/email/templates",
    );
    expect(post).toBeTruthy();
    expect(post?.body).toMatchObject({
      name: "Bienvenida",
      subject: "Hola cliente",
      body: "Bienvenido a la tienda",
    });
  });
});

test("enviar prueba pide destino y muestra el estado del spool", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  const promptSpy = vi
    .spyOn(window, "prompt")
    .mockReturnValue("cliente@example.invalid");
  await renderSection([templateFixture()], captured);

  await waitFor(() =>
    expect(screen.getAllByText("Seguimiento de presupuesto").length).toBeGreaterThanOrEqual(1),
  );
  await user.click(screen.getByRole("button", { name: "Enviar prueba" }));

  await waitFor(() => {
    const post = captured.find((request) => request.path.endsWith("/send-test"));
    expect(post).toBeTruthy();
    expect(post?.body).toMatchObject({ to: "cliente@example.invalid" });
  });
  // El token se muestra recortado a 8 caracteres en el flash.
  await waitFor(() => expect(screen.getByText(/tracking tk-abc1/)).toBeTruthy());
  promptSpy.mockRestore();
});

test("guardar la configuración de email envía el PUT", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderSection([], captured);

  await waitFor(() => expect(screen.getByText("Equipo")).toBeTruthy());
  await user.clear(screen.getByLabelText("Firma de instalación"));
  await user.type(
    screen.getByLabelText("Firma de instalación"),
    "Un saludo,\nVentas BTOP",
  );
  await user.click(screen.getByRole("button", { name: "Guardar configuración" }));

  await waitFor(() => {
    const put = captured.find(
      (request) => request.method === "PUT" && request.path === "/email/settings",
    );
    expect(put).toBeTruthy();
    expect(put?.body).toMatchObject({ signature: "Un saludo,\nVentas BTOP" });
  });
});

test("desactivar y eliminar una plantilla envían PATCH y DELETE", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  await renderSection([templateFixture()], captured);

  await waitFor(() =>
    expect(screen.getByText("Seguimiento de presupuesto")).toBeTruthy(),
  );
  await user.click(screen.getByRole("button", { name: "Desactivar" }));

  await waitFor(() => {
    const patch = captured.find(
      (request) =>
        request.method === "PATCH" && request.path === "/email/templates/tpl-1",
    );
    expect(patch).toBeTruthy();
    expect(patch?.body).toMatchObject({ is_active: false });
  });

  await user.click(screen.getByRole("button", { name: "Eliminar" }));
  await waitFor(() => {
    const del = captured.find(
      (request) =>
        request.method === "DELETE" && request.path === "/email/templates/tpl-1",
    );
    expect(del).toBeTruthy();
  });
  confirmSpy.mockRestore();
});
