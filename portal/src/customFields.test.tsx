import { expect, test } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CustomFieldsSection, CustomFieldDefinition } from "./customFields";

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

function fieldFixture(overrides: Partial<CustomFieldDefinition> = {}): CustomFieldDefinition {
  return {
    id: "field-1",
    key: "sector",
    label: "Sector",
    entity_type: "lead",
    field_type: "text",
    options: null,
    required: false,
    visibility: "all",
    position: 1,
    is_active: true,
    created_at: "2026-08-16T08:00:00",
    ...overrides,
  };
}

async function renderSection(
  fields: CustomFieldDefinition[],
  captured: CapturedRequest[] = [],
) {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? (JSON.parse(String(init.body)) as unknown) : undefined;
    captured.push({ path, method, body });
    if (method === "GET" && path === "/custom-fields") return response(fields);
    if (method === "POST" && path === "/custom-fields") {
      return response(fieldFixture(body as Partial<CustomFieldDefinition>), 201);
    }
    if (method === "PATCH" && path.startsWith("/custom-fields/")) {
      return response(fieldFixture(body as Partial<CustomFieldDefinition>));
    }
    return response({ detail: "no encontrado" }, 404);
  }) as typeof fetch;

  render(<CustomFieldsSection token="token-test" refreshRevision={0} />);
}

test("lista las definiciones de campos con tipo y visibilidad", async () => {
  await renderSection([
    fieldFixture(),
    fieldFixture({
      id: "field-2",
      key: "prioridad",
      label: "Prioridad",
      field_type: "select",
      options: ["Alta", "Baja"],
      visibility: "operators",
    }),
  ]);

  await waitFor(() => expect(screen.getByText("sector")).toBeTruthy());
  expect(screen.getByText("Sector")).toBeTruthy();
  // «Texto» aparece en la tabla y en el formulario, así que se admite >1.
  expect(screen.getAllByText("Texto").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(/Prioridad/)).toBeTruthy();
  expect(screen.getByText(/Alta, Baja/)).toBeTruthy();
  expect(screen.getAllByText("Operadores o superior").length).toBeGreaterThanOrEqual(1);
});

test("crear un campo envía el POST con la definición y audita", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderSection([], captured);

  await waitFor(() =>
    expect(screen.getByText(/Aún no hay campos personalizados/)).toBeTruthy(),
  );

  await user.type(screen.getByLabelText("Clave del nuevo campo"), "zona");
  await user.type(screen.getByLabelText("Etiqueta del nuevo campo"), "Zona geográfica");
  await user.click(screen.getByRole("button", { name: "Crear campo" }));

  await waitFor(() => {
    const post = captured.find(
      (request) => request.method === "POST" && request.path === "/custom-fields",
    );
    expect(post).toBeTruthy();
    expect(post?.body).toMatchObject({
      key: "zona",
      label: "Zona geográfica",
      entity_type: "lead",
      field_type: "text",
    });
  });
});

test("desactivar un campo envía el PATCH is_active=false", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderSection([fieldFixture()], captured);

  await waitFor(() => expect(screen.getByText("sector")).toBeTruthy());
  await user.click(screen.getByRole("button", { name: "Desactivar" }));

  await waitFor(() => {
    const patch = captured.find(
      (request) => request.method === "PATCH" && request.path === "/custom-fields/field-1",
    );
    expect(patch).toBeTruthy();
    expect(patch?.body).toMatchObject({ is_active: false });
  });
});

test("un campo select muestra el editor de opciones al crearlo", async () => {
  const user = userEvent.setup();
  await renderSection([]);

  await waitFor(() =>
    expect(screen.getByText(/Aún no hay campos personalizados/)).toBeTruthy(),
  );
  await user.selectOptions(screen.getByLabelText("Tipo del nuevo campo"), "select");
  expect(
    screen.getByLabelText("Opciones del campo select separadas por comas"),
  ).toBeTruthy();
});
