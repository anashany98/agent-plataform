/**
 * Evals Fase B (bloque 4): RBAC del portal.
 *
 * - Cada enlace de la navegación apunta a una sección renderizada (D-027).
 * - La navegación se filtra por rol: viewer solo lee, comercial opera
 *   (aprobaciones + clientes), admin gestiona todo (T-024).
 * - Carga parcial por rol: el viewer no llama a /costs ni /approvals y un
 *   403 de una sección nunca tumba el resto del panel.
 * - La sección Clientes lista leads y crea nuevos (CRUD mínimo comercial).
 * - Login y panel accesibles (axe).
 */
import { expect, test } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import App from "./App";

type MockResponse = { status: number; body: unknown };

function mockApi(routes: Record<string, MockResponse>) {
  const calls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push(`${method} ${url}`);
    for (const [suffix, response] of Object.entries(routes)) {
      if (url.endsWith(suffix)) {
        return new Response(JSON.stringify(response.body), {
          status: response.status,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response(JSON.stringify({ detail: "Ruta no mockeada" }), {
      status: 500,
    });
  }) as typeof fetch;
  return calls;
}

function loginSession(role: string = "provider_admin") {
  sessionStorage.setItem("agent_token", "token-test");
  sessionStorage.setItem("agent_user", role === "viewer" ? "viewer" : "admin");
  sessionStorage.setItem("agent_role", role);
  sessionStorage.setItem("agent_must_change", "false");
}

function dashboardBody(role: string) {
  const operator = [
    "provider_admin",
    "client_admin",
    "supervisor",
    "commercial",
    "support",
    "operator",
  ].includes(role);
  const admin = ["provider_admin", "client_admin"].includes(role);
  const counts: Record<string, number> = {
    products: 2,
    customers: 1,
    quotes: 1,
    orders: 0,
  };
  if (operator) counts.pending_approvals = 1;
  return {
    installation_id: "test-installation",
    installed_version: "0.9.1",
    pilot_mode: false,
    role,
    permissions: {
      approve: operator,
      manage_leads: operator,
      manage_users: admin,
      view_costs: admin,
      import_catalog: admin,
    },
    integrations: {
      prestashop: "not_configured",
      activepieces: "not_configured",
    },
    counts,
  };
}

const COSTS_BODY = {
  total_executions: 0,
  total_tokens_consumed: 0,
  total_estimated_cost_usd: 0,
  avg_latency_ms: 0,
  simulated_executions: 0,
};

const LEADS_BODY = [
  {
    id: "lead-1",
    email: "cliente-1@example.invalid",
    first_name: "Cliente Uno",
    phone: "+34600000001",
    company_name: "Corp A",
    source: "local",
    status: "new",
    created_at: "2026-08-10T10:00:00",
    opportunities: [
      {
        id: "opp-1",
        name: "Presupuesto Q-1",
        stage: "new",
        status: "open",
        monetary_value: 136,
        currency: "EUR",
        external_reference: "Q-1",
        notes_count: 1,
        created_at: "2026-08-10T10:00:00",
      },
    ],
  },
];

function routesFor(role: string): Record<string, MockResponse> {
  return {
    "/dashboard": { status: 200, body: dashboardBody(role) },
    "/costs": { status: 200, body: COSTS_BODY },
    "/approvals?status_filter=pending": { status: 200, body: [] },
    "/tools/products": {
      status: 200,
      body: [
        {
          id: "prod-1",
          sku: "SKU-0001",
          name: "Producto real",
          category: "Industrial",
          unit_price: 10,
          tax_rate: 0.21,
          available_stock: 5,
          source: "local",
        },
      ],
    },
    "/rag/documents": {
      status: 200,
      body: {
        documents: [
          {
            id: "doc-1",
            file_name: "manual.txt",
            mime_type: "text/plain",
            classification: "internal",
            dlp_findings: [],
            created_at: "2026-08-03T10:00:00",
          },
        ],
      },
    },
    "/agents": {
      status: 200,
      body: {
        status: "success",
        agents: [
          {
            agent_id: "sales_agent",
            name: "Agente comercial",
            purpose: "Recomendación de productos",
          },
        ],
      },
    },
    "/leads": { status: 200, body: LEADS_BODY },
    "/users": {
      status: 200,
      body: [
        {
          id: "u1",
          username: "admin",
          role: "provider_admin",
          is_active: true,
          must_change_password: false,
        },
      ],
    },
  };
}

async function waitForDashboard() {
  await waitFor(() => {
    expect(screen.getAllByText("Resumen operativo").length).toBeGreaterThan(0);
  });
}

test("el login es accesible y muestra errores del servidor", async () => {
  mockApi({
    "/auth/login": { status: 401, body: { detail: "Credenciales inválidas" } },
  });
  const { container } = render(<App />);

  expect(
    await screen.findByRole("heading", { name: "Plataforma de agentes IA" }),
  ).toBeTruthy();
  const results = await axe(container);
  expect(results.violations).toEqual([]);

  await userEvent.type(
    screen.getByLabelText("Contraseña"),
    "una-password-invalida",
  );
  await userEvent.click(screen.getByRole("button", { name: "Acceder" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain(
    "Credenciales inválidas",
  );
});

test("cada enlace de navegación apunta a una sección renderizada", async () => {
  loginSession("provider_admin");
  mockApi(routesFor("provider_admin"));
  const { container } = render(<App />);

  await waitForDashboard();

  const links = Array.from(container.querySelectorAll('nav a[href^="#"]'));
  expect(links.length).toBe(8);
  for (const link of links) {
    const targetId = (link.getAttribute("href") ?? "").slice(1);
    const target = container.querySelector(`#${targetId}`);
    expect(
      target,
      `El ancla ${targetId} debe tener una sección de destino`,
    ).not.toBeNull();
  }
});

test("viewer solo ve secciones de lectura y no llama a rutas sensibles", async () => {
  loginSession("viewer");
  const calls = mockApi(routesFor("viewer"));
  const { container } = render(<App />);

  await waitForDashboard();

  const labels = Array.from(container.querySelectorAll("nav a")).map(
    (link) => link.textContent,
  );
  expect(labels).toContain("Resumen");
  expect(labels).toContain("Productos");
  expect(labels).not.toContain("Aprobaciones");
  expect(labels).not.toContain("Clientes");
  expect(labels).not.toContain("Usuarios y permisos");

  expect(calls.some((call) => call.includes("/costs"))).toBe(false);
  expect(calls.some((call) => call.includes("/approvals"))).toBe(false);
  expect(calls.some((call) => call.includes("/leads"))).toBe(false);
  expect(calls.some((call) => call.includes("/dashboard"))).toBe(true);
});

test("commercial opera aprobaciones y clientes pero no usuarios ni costes", async () => {
  loginSession("commercial");
  const calls = mockApi(routesFor("commercial"));
  const { container } = render(<App />);

  await waitForDashboard();

  const labels = Array.from(container.querySelectorAll("nav a")).map(
    (link) => link.textContent,
  );
  expect(labels).toContain("Aprobaciones");
  expect(labels).toContain("Clientes");
  expect(labels).not.toContain("Usuarios y permisos");

  expect(calls.some((call) => call.includes("/approvals"))).toBe(true);
  expect(calls.some((call) => call.includes("/costs"))).toBe(false);

  await userEvent.click(screen.getByRole("link", { name: "Clientes" }));
  expect(await screen.findByText("cliente-1@example.invalid")).toBeTruthy();
});

test("admin ve todas las secciones y carga costes", async () => {
  loginSession("provider_admin");
  const calls = mockApi(routesFor("provider_admin"));
  const { container } = render(<App />);

  await waitForDashboard();

  expect(container.querySelectorAll('nav a[href^="#"]').length).toBe(8);
  expect(calls.some((call) => call.includes("/costs"))).toBe(true);
  expect(calls.some((call) => call.includes("/approvals"))).toBe(true);
});

test("la sección Clientes lista leads y crea uno nuevo", async () => {
  loginSession("commercial");
  const calls = mockApi({
    ...routesFor("commercial"),
    "/leads": { status: 200, body: LEADS_BODY },
  });
  render(<App />);

  await waitForDashboard();
  await userEvent.click(screen.getByRole("link", { name: "Clientes" }));
  expect(await screen.findByText("cliente-1@example.invalid")).toBeTruthy();
  expect(screen.getByText("Presupuesto Q-1 · 136.00 EUR")).toBeTruthy();

  await userEvent.type(screen.getByLabelText("Email"), "nuevo@example.invalid");
  await userEvent.type(screen.getByLabelText("Nombre"), "Nuevo Cliente");
  await userEvent.click(screen.getByRole("button", { name: "Crear lead" }));

  await waitFor(() => {
    expect(
      calls.some((call) => call.startsWith("POST") && call.includes("/leads")),
    ).toBe(true);
  });
});

test("un 403 de una sección no tumba el resto del panel", async () => {
  loginSession("provider_admin");
  mockApi({
    ...routesFor("provider_admin"),
    "/costs": { status: 403, body: { detail: "Permisos insuficientes" } },
  });
  render(<App />);

  await waitForDashboard();
  // El resumen sigue visible aunque los costes fallen.
  expect(screen.getAllByText("Resumen operativo").length).toBeGreaterThan(0);
});

test("los módulos muestran estado de error explícito cuando la API falla", async () => {
  loginSession("provider_admin");
  mockApi({
    ...routesFor("provider_admin"),
    "/users": { status: 403, body: { detail: "Permisos insuficientes" } },
  });
  render(<App />);

  await userEvent.click(
    await screen.findByRole("link", { name: "Usuarios y permisos" }),
  );
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("Permisos insuficientes");
  expect(alert.textContent).toContain("rol administrador");
});

test("las aprobaciones pendientes permiten decidir y el panel es accesible", async () => {
  loginSession("provider_admin");
  const calls = mockApi({
    ...routesFor("provider_admin"),
    "/approvals?status_filter=pending": {
      status: 200,
      body: [
        {
          id: "appr-1",
          action_type: "issue_invoice",
          target_key: "INV-001",
          status: "pending",
          payload: {},
          created_at: "2026-08-03T10:00:00",
        },
      ],
    },
    "/approvals/appr-1/approve": { status: 200, body: { status: "approved" } },
  });
  const { container } = render(<App />);

  await userEvent.click(
    await screen.findByRole("link", { name: "Aprobaciones" }),
  );
  expect(await screen.findByText("Aprobar borrador de factura")).toBeTruthy();

  await userEvent.click(screen.getByRole("button", { name: "Aprobar" }));
  await waitFor(() => {
    expect(
      calls.some((call) => call.includes("/approvals/appr-1/approve")),
    ).toBe(true);
  });

  const results = await axe(container);
  expect(results.violations).toEqual([]);
});
