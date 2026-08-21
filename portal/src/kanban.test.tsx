import { expect, test } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KanbanSection, PipelineBoard } from "./kanban";

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

function boardFixture(overrides: Partial<PipelineBoard> = {}): PipelineBoard {
  return {
    stages: [
      {
        key: "new",
        name: "Nuevo",
        position: 0,
        probability: 10,
        opportunities: [
          {
            id: "opp-1",
            lead_id: "lead-1",
            name: "Cubo 20L",
            stage: "new",
            status: "open",
            monetary_value: 320,
            currency: "EUR",
            probability: null,
            external_reference: null,
            notes_count: 1,
            lead_email: "a@example.invalid",
            lead_first_name: "Ana",
            lead_company: "Ferretería Sur",
            assigned_to: null,
            created_at: "2026-08-15T08:00:00",
          },
        ],
      },
      {
        key: "won",
        name: "Ganado",
        position: 1,
        probability: 100,
        opportunities: [],
      },
    ],
    unassigned_leads: [
      {
        id: "lead-9",
        email: "nuevo@example.invalid",
        first_name: "Nuevo",
        company_name: "Empresa X",
        source: "local",
        status: "new",
        opportunities: [],
        score: 45,
        score_signals: [
          { kind: "source", points: 10, detail: "local" },
          { kind: "age", points: 15, detail: "0.0 días" },
          { kind: "opportunities", points: 0, detail: "sin oportunidades abiertas" },
        ],
        created_at: "2026-08-16T08:00:00",
      },
    ],
    users: [
      { id: "user-1", username: "carmen", role: "commercial" },
      { id: "user-2", username: "admin", role: "client_admin" },
    ],
    ...overrides,
  };
}

function mockDataTransfer(): DataTransfer {
  return {
    effectAllowed: "",
    dropEffect: "",
    setData: () => undefined,
    getData: () => "",
    clearData: () => undefined,
    setDragImage: () => undefined,
    types: [],
    items: [] as unknown as DataTransferItemList,
    files: [] as unknown as FileList,
  } as unknown as DataTransfer;
}

async function renderKanban(overrides: {
  board?: PipelineBoard;
  isAdmin?: boolean;
  captured?: CapturedRequest[];
} = {}) {
  const { board = boardFixture(), isAdmin = true, captured = [] } = overrides;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? (JSON.parse(String(init.body)) as unknown) : undefined;
    captured.push({ path, method, body });
    if (path === "/pipeline/board") return response(board);
    if (path === "/leads/lead-1/timeline") {
      return response({
        lead: {
          id: "lead-1",
          email: "a@example.invalid",
          first_name: "Ana",
          company_name: "Ferretería Sur",
          source: "local",
          status: "open",
          created_at: "2026-08-15T08:00:00",
        },
        timeline: [
          {
            kind: "opportunity_created",
            title: "Oportunidad creada",
            detail: "Cubo 20L · 320.00 EUR",
            created_at: "2026-08-15T08:00:00",
            actor: null,
          },
        ],
      });
    }
    if (method === "POST" && path === "/opportunities/opp-1/close") {
      const payload = body as { outcome: string };
      return response({
        id: "opp-1",
        stage: payload.outcome === "won" ? "won" : "lost",
        status: payload.outcome,
        probability: payload.outcome === "won" ? 100 : 0,
        lost_reason: payload.outcome === "lost" ? (body as { lost_reason?: string }).lost_reason ?? null : null,
        won_at: payload.outcome === "won" ? "2026-08-16T10:00:00" : null,
        lost_at: payload.outcome === "lost" ? "2026-08-16T10:00:00" : null,
      });
    }
    if (method === "PATCH" && path.startsWith("/opportunities/")) {
      const target = (body as { stage: string }).stage;
      return response({ id: "opp-1", stage: target, changed: true });
    }
    if (method === "PATCH" && path.startsWith("/leads/")) {
      return response({ id: "lead-9", assigned_to: (body as { user_id: string }).user_id, changed: true });
    }
    if (method === "PUT" && path === "/pipeline/stages") {
      return response(
        (body as { names: string[] }).names.map((name, position) => ({
          key: `key-${position}`,
          name,
          position,
        })),
      );
    }
    return response({}, 404);
  }) as typeof fetch;

  const utils = render(
    <KanbanSection token="token-test" isAdmin={isAdmin} refreshRevision={1} />,
  );
  await screen.findByRole("heading", { name: "Pipeline comercial" });
  return { ...utils, captured };
}

test("el kanban muestra columnas, tarjetas y cola de leads sin asignar", async () => {
  await renderKanban();
  expect(screen.getByRole("list", { name: "Tablero de etapas" })).toBeTruthy();
  expect(screen.getByText("Nuevo")).toBeTruthy();
  expect(screen.getByText("Ganado")).toBeTruthy();
  expect(screen.getByText("Cubo 20L")).toBeTruthy();
  expect(screen.getByText("Leads sin asignar")).toBeTruthy();
  expect(screen.getByText("nuevo@example.invalid")).toBeTruthy();
});

test("la cola expone la puntuación de cada lead con sus señales", async () => {
  await renderKanban();
  expect(screen.getByText("Puntuación")).toBeTruthy();
  const badge = screen.getByLabelText("Puntuación 45 sobre 100");
  expect(badge.textContent).toBe("45");
  expect(badge.className).toContain("score-medium");
});

test("mover una tarjeta a otra columna llama al PATCH auditado y recarga", async () => {
  const captured: CapturedRequest[] = [];
  await renderKanban({ captured });
  const card = screen.getByLabelText(/Cubo 20L/);
  const wonColumn = screen
    .getAllByRole("listitem")
    .find((node) => within(node as HTMLElement).queryByText("Ganado"));

  const won = wonColumn as HTMLElement;
  fireEvent.dragStart(card, { dataTransfer: mockDataTransfer() });
  fireEvent.dragOver(won, { dataTransfer: mockDataTransfer() });
  fireEvent.drop(won, { dataTransfer: mockDataTransfer() });
  fireEvent.dragEnd(card);

  await waitFor(() => {
    const move = captured.find(
      (req) => req.method === "PATCH" && req.path === "/opportunities/opp-1",
    );
    expect(move).toBeTruthy();
    expect(move?.body).toEqual({ stage: "won" });
  });
  // Tras recargar, la tarjeta vuelve a su estado original (el mock no muta el fixture).
  expect(screen.getByText("Cubo 20L")).toBeTruthy();
});

test("clic en una tarjeta abre la ficha del lead con su timeline", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderKanban({ captured });
  const card = await screen.findByLabelText(/Cubo 20L/);
  await user.click(card);
  await screen.findByRole("dialog", { name: "Ficha del lead" });
  expect(screen.getByText("Oportunidad creada")).toBeTruthy();
  expect(screen.getByText("Cubo 20L · 320.00 EUR")).toBeTruthy();
  expect(
    captured.some((req) => req.path === "/leads/lead-1/timeline"),
  ).toBe(true);
});

test("asignar un lead de la cola llama al PATCH de asignación auditado", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderKanban({ captured });
  const select = screen.getByLabelText("Asignar lead nuevo@example.invalid");
  await user.selectOptions(select, "user-1");

  await waitFor(() => {
    const assign = captured.find(
      (req) => req.method === "PATCH" && req.path === "/leads/lead-9/assign",
    );
    expect(assign).toBeTruthy();
    expect(assign?.body).toEqual({ user_id: "user-1" });
  });
});

test("un viewer no admin no ve el editor de etapas", async () => {
  await renderKanban({ isAdmin: false });
  expect(
    screen.queryByRole("button", { name: "Editar etapas" }),
  ).toBeNull();
});

test("el admin guarda el pipeline reconfigurado con PUT auditado", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderKanban({ captured });
  await user.click(screen.getByRole("button", { name: "Editar etapas" }));
  const nameInput = screen.getByLabelText("Nombre de la etapa 1");
  await user.clear(nameInput);
  await user.type(nameInput, "Contactado");
  await user.type(
    screen.getByLabelText("Nombre de la nueva etapa"),
    "Cierre",
  );
  await user.click(screen.getByRole("button", { name: "Añadir etapa" }));
  await user.click(screen.getByRole("button", { name: "Guardar pipeline" }));

  await waitFor(() => {
    const put = captured.find(
      (req) => req.method === "PUT" && req.path === "/pipeline/stages",
    );
    expect(put).toBeTruthy();
    expect(put?.body).toEqual({ names: ["Contactado", "Ganado", "Cierre"] });
  });
  expect(screen.getByText("Pipeline actualizado. Cambio auditado.")).toBeTruthy();
});

test("cerrar una oportunidad como perdida envía el motivo y recarga", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderKanban({ captured });
  await user.click(screen.getByRole("button", { name: "Cerrar" }));
  expect(screen.getByText("Cerrar «Cubo 20L»")).toBeTruthy();
  await user.selectOptions(
    screen.getByLabelText("Resultado"),
    "lost",
  );
  await user.type(
    screen.getByLabelText("Motivo de pérdida"),
    "Precio demasiado alto",
  );
  await user.click(screen.getByRole("button", { name: "Confirmar cierre" }));

  await waitFor(() => {
    const post = captured.find(
      (req) => req.method === "POST" && req.path === "/opportunities/opp-1/close",
    );
    expect(post).toBeTruthy();
    expect(post?.body).toEqual({
      outcome: "lost",
      lost_reason: "Precio demasiado alto",
      probability: null,
    });
  });
  expect(screen.getByText(/marcada como perdida/)).toBeTruthy();
});
