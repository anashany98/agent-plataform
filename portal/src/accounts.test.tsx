import { expect, test } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AccountsSection, AccountRow, AccountDetail } from "./accounts";

type CapturedRequest = {
  path: string;
  method: string;
  body?: unknown;
};

function requestPath(input: RequestInfo | URL): string {
  const url = new URL(String(input), "http://portal.test");
  return `${url.pathname}${url.search}`.replace(/^\/api\/bridge/, "");
}

function accountFixture(overrides: Partial<AccountRow> = {}): AccountRow {
  return {
    id: "acc-1",
    name: "Acme Industrial",
    industry: "Manufactura",
    website: "https://acme.test",
    phone: null,
    city: "Madrid",
    country: "ES",
    notes: null,
    is_active: true,
    contact_count: 2,
    open_value: 1250.0,
    open_count: 3,
    won_value: 500.0,
    lost_value: 200.0,
    created_at: "2026-08-10T08:00:00",
    updated_at: "2026-08-10T08:00:00",
    ...overrides,
  };
}

function detailFixture(): AccountDetail {
  return {
    ...accountFixture(),
    contacts: [
      {
        id: "contact-1",
        account_id: "acc-1",
        full_name: "Ana Pérez",
        email: "ana@acme.test",
        phone: null,
        job_title: "Compradora",
        is_primary: true,
        merged_into_contact_id: null,
        lead_count: 1,
        created_at: "2026-08-10T08:00:00",
      },
    ],
    opportunities: [
      {
        id: "opp-1",
        name: "Cubo 20L",
        stage: "quote",
        status: "open",
        monetary_value: 320,
        currency: "EUR",
        probability: 40,
        created_at: "2026-08-11T08:00:00",
      },
    ],
  };
}

async function renderAccounts(captured: CapturedRequest[] = []) {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    const body = init?.body
      ? (JSON.parse(String(init.body)) as unknown)
      : undefined;
    captured.push({ path, method, body });
    if (method === "GET" && path === "/accounts") {
      return new Response(JSON.stringify([accountFixture()]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (method === "GET" && path === "/accounts/acc-1") {
      return new Response(JSON.stringify(detailFixture()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (method === "POST" && path === "/accounts") {
      return new Response(
        JSON.stringify(
          accountFixture({ name: (body as { name: string }).name }),
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (method === "POST" && path === "/contacts") {
      return new Response(
        JSON.stringify({
          id: "contact-2",
          account_id: "acc-1",
          ...(body as object),
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    return new Response(JSON.stringify({ detail: "no encontrado" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  render(<AccountsSection token="token-test" refreshRevision={0} />);
  await screen.findByText("Acme Industrial");
}

test("lista las cuentas con contactos y métricas de pipeline", async () => {
  await renderAccounts();
  expect(screen.getByText("Manufactura")).toBeTruthy();
  expect(screen.getByText("Madrid")).toBeTruthy();
  expect(screen.getByText("3 · 1250.00 EUR")).toBeTruthy();
  expect(screen.getByText("500.00 EUR")).toBeTruthy();
  expect(screen.getByText("1 cuentas")).toBeTruthy();
});

test("crear una cuenta envía el POST auditado y refresca", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderAccounts(captured);
  await user.type(screen.getByLabelText("Nombre de la cuenta"), "BTOP Digital");
  await user.type(screen.getByLabelText("Sector"), "Software");
  await user.click(screen.getByRole("button", { name: "Crear cuenta" }));
  await waitFor(() => {
    const post = captured.find(
      (req) => req.method === "POST" && req.path === "/accounts",
    );
    expect(post).toBeTruthy();
    expect(post?.body).toMatchObject({
      name: "BTOP Digital",
      industry: "Software",
    });
  });
});

test("abrir la ficha muestra contactos, oportunidades y permite crear contacto", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderAccounts(captured);
  fireEvent.click(screen.getByText("Acme Industrial"));
  await waitFor(() => {
    expect(screen.getByText(/Ana Pérez/)).toBeTruthy();
  });
  expect(
    screen.getByText("Compradora · ana@acme.test · — · 1 leads"),
  ).toBeTruthy();
  expect(screen.getByText("Cubo 20L")).toBeTruthy();
  expect(screen.getByText(/320.00 EUR/)).toBeTruthy();

  await user.type(screen.getByLabelText("Nombre del contacto"), "Luis");
  await user.type(
    screen.getByLabelText("Email del contacto"),
    "luis@acme.test",
  );
  await user.click(screen.getByRole("button", { name: "Añadir contacto" }));
  await waitFor(() => {
    const post = captured.find(
      (req) => req.method === "POST" && req.path === "/contacts",
    );
    expect(post).toBeTruthy();
    expect(post?.body).toMatchObject({
      account_id: "acc-1",
      first_name: "Luis",
      email: "luis@acme.test",
    });
  });
});
