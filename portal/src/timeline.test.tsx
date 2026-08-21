import { expect, test } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LeadTimelineDrawer, LeadTimelineData } from "./timeline";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function timelineFixture(): LeadTimelineData {
  return {
    lead: {
      id: "lead-1",
      email: "cliente@example.invalid",
      first_name: "Ana",
      company_name: "Ferretería Sur",
      source: "local",
      status: "open",
      created_at: "2026-08-10T08:00:00",
    },
    timeline: [
      {
        kind: "email_sent",
        title: "Email enviado",
        detail: "Proveedor smtp",
        created_at: "2026-08-16T10:00:00",
        actor: "admin",
      },
      {
        kind: "stage_changed",
        title: "Etapa cambiada",
        detail: "Nuevo → Calificado",
        created_at: "2026-08-15T09:00:00",
        actor: "carmen",
        opportunity_name: "Presupuesto Cubo",
      },
      {
        kind: "lead_created",
        title: "Lead creado",
        detail: "Origen: local",
        created_at: "2026-08-10T08:00:00",
        actor: null,
      },
    ],
  };
}

async function renderDrawer(
  data: LeadTimelineData = timelineFixture(),
  leadId: string | null = "lead-1",
) {
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://portal.test");
    if (
      url.pathname.replace(/^\/api\/bridge/, "") === "/leads/lead-1/timeline"
    ) {
      return response(data);
    }
    return response({}, 404);
  }) as typeof fetch;

  const utils = render(
    <LeadTimelineDrawer
      token="token-test"
      leadId={leadId}
      onClose={() => undefined}
    />,
  );
  if (leadId) await screen.findByText("Ana");
  return utils;
}

test("la ficha muestra los datos del lead y el historial cronológico", async () => {
  await renderDrawer();
  expect(screen.getByRole("dialog", { name: "Ficha del lead" })).toBeTruthy();
  expect(screen.getByText("cliente@example.invalid")).toBeTruthy();
  expect(screen.getByText("Ferretería Sur")).toBeTruthy();
  expect(screen.getByText("Historial")).toBeTruthy();
  expect(screen.getByText("Email enviado")).toBeTruthy();
  expect(screen.getByText("Proveedor smtp")).toBeTruthy();
  expect(screen.getByText("Etapa cambiada")).toBeTruthy();
  expect(screen.getByText("Nuevo → Calificado")).toBeTruthy();
  expect(screen.getByText("Presupuesto Cubo")).toBeTruthy();
  expect(screen.getByText("Lead creado")).toBeTruthy();
  expect(screen.getByText("Origen: local")).toBeTruthy();
});

test("sin leadId no renderiza el drawer", () => {
  globalThis.fetch = (async () => response({}, 404)) as typeof fetch;
  const { container } = render(
    <LeadTimelineDrawer token="t" leadId={null} onClose={() => undefined} />,
  );
  expect(container.querySelector(".lead-drawer")).toBeNull();
});

test("el drawer vacío muestra el estado sin interacciones", async () => {
  const data = timelineFixture();
  data.timeline = [];
  await renderDrawer(data);
  expect(
    screen.getByText("Sin interacciones registradas todavía."),
  ).toBeTruthy();
});

test("Esc cierra la ficha", async () => {
  const user = userEvent.setup();
  let closed = false;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://portal.test");
    if (
      url.pathname.replace(/^\/api\/bridge/, "") === "/leads/lead-1/timeline"
    ) {
      return response(timelineFixture());
    }
    return response({}, 404);
  }) as typeof fetch;
  render(
    <LeadTimelineDrawer
      token="t"
      leadId="lead-1"
      onClose={() => {
        closed = true;
      }}
    />,
  );
  await screen.findByText("Ana");
  await user.keyboard("{Escape}");
  await waitFor(() => expect(closed).toBe(true));
});

test("la ficha muestra el error si la API falla", async () => {
  globalThis.fetch = (async () =>
    response({ detail: "Lead no encontrado" }, 404)) as typeof fetch;
  render(
    <LeadTimelineDrawer
      token="t"
      leadId="lead-no-existe"
      onClose={() => undefined}
    />,
  );
  await waitFor(() => {
    expect(screen.getByText("Lead no encontrado")).toBeTruthy();
  });
});
