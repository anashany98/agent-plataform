/**
 * Evals Fase B (bloque 4): RBAC del portal.
 *
 * - Cada enlace de la navegación apunta a una sección renderizada (D-027).
 * - La navegación se filtra por rol: viewer solo lee, comercial opera ventas
 *   y clientes, y solo admin decide aprobaciones/configura módulos (T-024).
 * - Carga parcial por rol: el viewer no llama a /costs ni /approvals y un
 *   403 de una sección nunca tumba el resto del panel.
 * - Clientes, ventas, contenido, SEO, landings, tareas y agentes exponen sus
 *   contratos persistidos sin presentar borradores como acciones ejecutadas.
 * - Login y panel accesibles (axe).
 */
import { beforeEach, expect, test } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import App from "./App";
import { ONBOARDING_STORAGE_KEY } from "./onboarding";

// Los tests existentes asumen un usuario ya familiarizado: el onboarding
// guiado (T-072) queda marcado como completado y el modo avanzado queda
// activo para que la navegación completa (según RBAC) siga visible.
// Los tests específicos del onboarding y del modo simple controlan sus
// propias claves en onboarding.test.tsx y en los tests dedicados de abajo.
beforeEach(() => {
  window.localStorage.setItem(ONBOARDING_STORAGE_KEY, "done");
  window.localStorage.setItem("advanced-mode", "on");
});

type MockResponse = { status: number; body: unknown };

function mockApi(routes: Record<string, MockResponse>) {
  const calls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push(`${method} ${url}`);
    for (const [suffix, response] of Object.entries(routes)) {
      // Las URLs del cliente pueden ser absolutas (http://localhost/...):
      // el sufijo casa con el final, y la misma ruta con query string
      // (el catálogo paginado consulta /catalog/products?limit=...) también.
      if (
        url === suffix ||
        url.endsWith(suffix) ||
        url.includes(`${suffix}?`)
      ) {
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
      approve: admin,
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

const SYNC_HISTORY_BODY = {
  history: [
    {
      id: "sync-1",
      started_at: "2026-08-14T06:38:12",
      finished_at: "2026-08-14T06:39:04",
      duration_seconds: 51.645,
      since: "2026-08-13 14:25:51",
      incremental: true,
      status: "success",
      total_remote: 0,
      created: 0,
      updated: 0,
      unchanged: 0,
      error: null,
    },
    {
      id: "sync-2",
      started_at: "2026-08-14T05:10:00",
      finished_at: "2026-08-14T05:10:01",
      duration_seconds: 0.4,
      since: "2026-08-13 00:00:00",
      incremental: true,
      status: "skipped",
      total_remote: 0,
      created: 0,
      updated: 0,
      unchanged: 0,
      error: "Otro sync de PrestaShop en curso",
    },
  ],
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
    "/integrations/prestashop/sync/history?limit=8": {
      status: 200,
      body: SYNC_HISTORY_BODY,
    },
    "/approvals?status_filter=pending": { status: 200, body: [] },
    "/catalog/products": {
      status: 200,
      body: {
        items: [
          {
            id: "prod-1",
            sku: "SKU-0001",
            name: "Producto real",
            category: "Industrial",
            unit_price: 10,
            tax_rate: 0.21,
            available_stock: 5,
            source: "local",
            created_at: "2026-08-15T08:00:00",
            updated_at: "2026-08-15T08:00:00",
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      },
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
            status: "active",
          },
        ],
      },
    },
    "/customers?limit=100": {
      status: 200,
      body: {
        items: [
          {
            id: "cust-1",
            name: "Cliente Real",
            email: "ventas@example.invalid",
            phone: null,
            company: "Empresa Real",
            created_at: "2026-08-03T10:00:00",
          },
        ],
      },
    },
    "/quotes?limit=100": { status: 200, body: { items: [] } },
    "/orders?limit=100": { status: 200, body: { items: [] } },
    "/invoices?limit=100": { status: 200, body: { items: [] } },
    "/wiki/pages": { status: 200, body: { items: [] } },
    "/seo/projects": {
      status: 200,
      body: {
        items: [
          {
            id: "seo-1",
            name: "SEO real",
            domain: "example.invalid",
            configuration: {},
            status: "draft",
            version: 1,
            updated_at: "2026-08-03T10:00:00",
            analysis_engine: "deterministic_html_static_v1",
            external_crawler: "not_implemented",
          },
        ],
      },
    },
    "/landing-pages": { status: 200, body: { items: [] } },
    "/scheduled-tasks": { status: 200, body: { items: [] } },
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
    // Landing por defecto: el Asistente (chat universal).
    expect(screen.getAllByText("Asistente").length).toBeGreaterThan(0);
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

  await userEvent.type(screen.getByLabelText("Usuario"), "admin");
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
  expect(links.length).toBe(14); // 13 módulos + el Asistente (landing)
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
  expect(labels).toContain("Hoy");
  expect(labels).toContain("Productos");
  expect(labels).not.toContain("Aprobaciones");
  expect(labels).not.toContain("Clientes");
  expect(labels).not.toContain("Usuarios y permisos");

  expect(calls.some((call) => call.includes("/costs"))).toBe(false);
  expect(calls.some((call) => call.includes("/approvals"))).toBe(false);
  expect(calls.some((call) => call.includes("/leads"))).toBe(false);
  expect(calls.some((call) => call.includes("/dashboard"))).toBe(true);
});

test("commercial opera ventas y clientes pero no aprobaciones administrativas", async () => {
  loginSession("commercial");
  const calls = mockApi(routesFor("commercial"));
  const { container } = render(<App />);

  await waitForDashboard();

  const labels = Array.from(container.querySelectorAll("nav a")).map(
    (link) => link.textContent,
  );
  expect(labels).toContain("Clientes");
  expect(labels).toContain("Ventas y facturación");
  expect(labels).toContain("Contenido y SEO");
  expect(labels).not.toContain("Aprobaciones");
  expect(labels).not.toContain("Tareas programadas");
  expect(labels).not.toContain("Usuarios y permisos");

  expect(calls.some((call) => call.includes("/approvals"))).toBe(false);
  expect(calls.some((call) => call.includes("/costs"))).toBe(false);
  expect(calls.some((call) => call.includes("/customers"))).toBe(true);

  await userEvent.click(screen.getByRole("link", { name: "Clientes" }));
  expect(await screen.findByText("cliente-1@example.invalid")).toBeTruthy();
});

test("admin ve todas las secciones y carga costes", async () => {
  loginSession("provider_admin");
  const calls = mockApi(routesFor("provider_admin"));
  const { container } = render(<App />);

  await waitForDashboard();

  expect(container.querySelectorAll('nav a[href^="#"]').length).toBe(14); // incluye el Asistente
  expect(calls.some((call) => call.includes("/costs"))).toBe(true);
  expect(calls.some((call) => call.includes("/approvals"))).toBe(true);
});

test("el menú agrupa las secciones por intención", async () => {
  loginSession("provider_admin");
  mockApi(routesFor("provider_admin"));
  const { container } = render(<App />);

  await waitForDashboard();

  const groupLabels = Array.from(
    container.querySelectorAll(".nav-group-label"),
  ).map((element) => element.textContent);
  expect(groupLabels).toEqual([
    "Inicio",
    "Ventas",
    "Catálogo",
    "Marketing",
    "Ajustes",
  ]);
});

test("los grupos sin secciones permitidas por el rol no aparecen", async () => {
  loginSession("viewer");
  mockApi(routesFor("viewer"));
  const { container } = render(<App />);

  await waitForDashboard();

  const groupLabels = Array.from(
    container.querySelectorAll(".nav-group-label"),
  ).map((element) => element.textContent);
  expect(groupLabels).toContain("Inicio");
  expect(groupLabels).toContain("Catálogo");
  expect(groupLabels).not.toContain("Ventas");
});

test("el modo simple está activo por defecto y oculta los módulos técnicos", async () => {
  window.localStorage.removeItem("advanced-mode");
  loginSession("provider_admin");
  mockApi(routesFor("provider_admin"));
  const { container } = render(<App />);

  await waitForDashboard();

  const labels = Array.from(container.querySelectorAll("nav a")).map(
    (link) => link.textContent,
  );
  expect(labels).toContain("Asistente");
  expect(labels).toContain("Productos");
  expect(labels).toContain("Clientes");
  expect(labels).not.toContain("Webhooks salientes");
  expect(labels).not.toContain("Usuarios y permisos");
  expect(labels).not.toContain("Agentes de IA");
  // Automatizaciones es el panel amigable del motor (estado, «Ejecutar
  // ahora» y cola de reintentos): queda visible también en modo simple.
  expect(labels).toContain("Automatizaciones");
});

test("el toggle de modo avanzado revela y vuelve a ocultar los módulos técnicos", async () => {
  window.localStorage.removeItem("advanced-mode");
  loginSession("provider_admin");
  mockApi(routesFor("provider_admin"));
  render(<App />);

  await waitForDashboard();

  expect(screen.queryByRole("link", { name: "Webhooks salientes" })).toBeNull();

  await userEvent.click(
    screen.getByRole("button", { name: "Activar modo avanzado" }),
  );
  expect(
    await screen.findByRole("link", { name: "Webhooks salientes" }),
  ).toBeTruthy();
  expect(window.localStorage.getItem("advanced-mode")).toBe("on");

  await userEvent.click(
    screen.getByRole("button", { name: "Activar modo simple" }),
  );
  expect(screen.queryByRole("link", { name: "Webhooks salientes" })).toBeNull();
  expect(window.localStorage.getItem("advanced-mode")).toBe("off");
});

test("los nuevos módulos son navegables y no presentan violaciones axe básicas", async () => {
  loginSession("provider_admin");
  mockApi(routesFor("provider_admin"));
  const { container } = render(<App />);
  await waitForDashboard();

  for (const [linkName, title] of [
    ["Ventas y facturación", "Ventas y facturación"],
    ["Contenido y SEO", "Contenido, SEO y landings"],
    ["Tareas programadas", "Tareas programadas"],
    ["Agentes de IA", "Agentes de IA"],
  ]) {
    await userEvent.click(screen.getByRole("link", { name: linkName }));
    await waitFor(() => {
      expect(container.querySelector("main h1")?.textContent).toContain(title);
    });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  }
});

test("el panel muestra el historial de sincronización de PrestaShop", async () => {
  loginSession("provider_admin");
  const calls = mockApi(routesFor("provider_admin"));
  render(<App />);

  await waitForDashboard();

  expect(screen.getByText("Historial de sincronización")).toBeTruthy();
  expect(await screen.findByText("Éxito")).toBeTruthy();
  expect(screen.getByText("Omitido")).toBeTruthy();
  expect(
    calls.some((call) =>
      call.includes("/integrations/prestashop/sync/history"),
    ),
  ).toBe(true);
});

test("la sección Clientes lista leads y crea uno nuevo", async () => {
  loginSession("commercial");
  const calls = mockApi({
    ...routesFor("commercial"),
    "/leads": { status: 200, body: LEADS_BODY },
  });
  const { container } = render(<App />);

  await waitForDashboard();
  await userEvent.click(screen.getByRole("link", { name: "Clientes" }));
  expect(await screen.findByText("cliente-1@example.invalid")).toBeTruthy();
  expect(screen.getByText("Presupuesto Q-1 · 136.00 EUR")).toBeTruthy();

  const clientsSection = within(
    container.querySelector("#clientes") as HTMLElement,
  );
  await userEvent.type(
    clientsSection.getByLabelText("Email"),
    "nuevo@example.invalid",
  );
  await userEvent.type(
    clientsSection.getByLabelText("Nombre"),
    "Nuevo Cliente",
  );
  await userEvent.click(
    clientsSection.getByRole("button", { name: "Crear lead" }),
  );

  await waitFor(() => {
    expect(
      calls.some((call) => call.startsWith("POST") && call.includes("/leads")),
    ).toBe(true);
  });
});

test("el botón Exportar CSV descarga el fichero de leads", async () => {
  loginSession("commercial");
  const calls = mockApi({
    ...routesFor("commercial"),
    "/leads": { status: 200, body: LEADS_BODY },
    "/leads/export.csv": {
      status: 200,
      body: "email,first_name\ncliente-1@example.invalid,Cliente Uno",
    },
  });
  const createdUrls: string[] = [];
  const originalCreate = window.URL.createObjectURL;
  const originalRevoke = window.URL.revokeObjectURL;
  window.URL.createObjectURL = ((blob: Blob) => {
    createdUrls.push(`blob:mock-${blob.size}`);
    return createdUrls[createdUrls.length - 1];
  }) as typeof window.URL.createObjectURL;
  window.URL.revokeObjectURL = (() =>
    undefined) as typeof window.URL.revokeObjectURL;

  try {
    const { container } = render(<App />);
    await waitForDashboard();
    await userEvent.click(screen.getByRole("link", { name: "Clientes" }));

    const clientsSection = within(
      container.querySelector("#clientes") as HTMLElement,
    );
    await userEvent.click(
      clientsSection.getByRole("button", { name: "Exportar CSV" }),
    );

    await waitFor(() => {
      expect(calls.some((call) => call.includes("/leads/export.csv"))).toBe(
        true,
      );
    });
    expect(createdUrls.length).toBe(1);
  } finally {
    window.URL.createObjectURL = originalCreate;
    window.URL.revokeObjectURL = originalRevoke;
  }
});

test("un 403 de una sección no tumba el resto del panel", async () => {
  loginSession("provider_admin");
  mockApi({
    ...routesFor("provider_admin"),
    "/costs": { status: 403, body: { detail: "Permisos insuficientes" } },
  });
  render(<App />);

  await waitForDashboard();
  // El landing (Asistente) sigue visible aunque los costes fallen.
  expect(screen.getAllByText("Asistente").length).toBeGreaterThan(0);
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

test("la búsqueda semántica del catálogo muestra resultados con score", async () => {
  loginSession("provider_admin");
  const semanticUrl =
    "/tools/products/semantic?query=pantalla%20para%20jugar&top_k=10";
  const calls = mockApi({
    ...routesFor("provider_admin"),
    [semanticUrl]: {
      status: 200,
      body: {
        query: "pantalla para jugar",
        products: [
          {
            id: "prod-1",
            sku: "SKU-0001",
            name: "Monitor 27 pulgadas",
            category: "Informática",
            unit_price: 249.99,
            tax_rate: 0.21,
            available_stock: 3,
            source: "local",
            score: 0.647,
          },
          {
            id: "prod-2",
            sku: "SKU-0002",
            name: "Portátil Pro 14",
            category: "Informática",
            unit_price: 899.99,
            tax_rate: 0.21,
            available_stock: 10,
            source: "local",
            score: 0.616,
          },
        ],
      },
    },
  });
  render(<App />);

  await waitForDashboard();
  await userEvent.click(screen.getByRole("link", { name: "Productos" }));
  await userEvent.type(
    await screen.findByLabelText("Consulta semántica"),
    "pantalla para jugar",
  );
  await userEvent.click(screen.getByRole("button", { name: "Buscar" }));

  expect(await screen.findByText("Monitor 27 pulgadas")).toBeTruthy();
  expect(screen.getByText("Portátil Pro 14")).toBeTruthy();
  // Scores de similitud como porcentaje (coseno sobre embeddings).
  expect(screen.getByText("64.7%")).toBeTruthy();
  expect(screen.getByText("61.6%")).toBeTruthy();
  expect(calls.some((call) => call.includes("/tools/products/semantic"))).toBe(
    true,
  );
});

test("la búsqueda semántica avisa de los tokens cortos descartados", async () => {
  loginSession("provider_admin");
  const semanticUrl =
    "/tools/products/semantic?query=de%20un%20escritorio&top_k=10";
  mockApi({
    ...routesFor("provider_admin"),
    [semanticUrl]: {
      status: 200,
      body: {
        query: "de un escritorio",
        products: [
          {
            id: "prod-1",
            sku: "SKU-0001",
            name: "Escritorio Modelo Demo",
            category: "Oficina",
            unit_price: 199.0,
            tax_rate: 0.21,
            available_stock: 5,
            source: "local",
            score: 0.71,
          },
        ],
        discarded_tokens: ["de", "un"],
      },
    },
  });
  render(<App />);

  await waitForDashboard();
  await userEvent.click(screen.getByRole("link", { name: "Productos" }));
  await userEvent.type(
    await screen.findByLabelText("Consulta semántica"),
    "de un escritorio",
  );
  await userEvent.click(screen.getByRole("button", { name: "Buscar" }));

  const note = await screen.findByLabelText("Tokens descartados");
  expect(note.textContent).toContain("“de”");
  expect(note.textContent).toContain("“un”");
  // El producto sigue mostrándose pese a los tokens descartados.
  expect(screen.getByText("Escritorio Modelo Demo")).toBeTruthy();
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
        {
          id: "appr-2",
          action_type: "agent_proposal:ceo_follow_up",
          action_label: "seguimiento a un lead frío",
          target_key: "lead-abc-123",
          target_label: "María Pérez",
          status: "pending",
          payload: {},
          created_at: "2026-08-03T11:00:00",
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
  // Las filas con labels en lenguaje llano los muestran en Acción y Objetivo,
  // conservando la clave cruda como referencia para la confirmación.
  expect(await screen.findByText("seguimiento a un lead frío")).toBeTruthy();
  expect(screen.getByText("María Pérez")).toBeTruthy();
  expect(screen.getByText("lead-abc-123")).toBeTruthy();

  await userEvent.click(
    screen.getByRole("button", { name: "Aprobar INV-001" }),
  );
  expect(calls.some((call) => call.includes("/approvals/appr-1/approve"))).toBe(
    false,
  );

  expect(
    await screen.findByRole("dialog", { name: "Confirmar aprobación" }),
  ).toBeTruthy();
  await userEvent.type(
    screen.getByLabelText("Escribe la referencia exacta para confirmar"),
    "INV-001",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Confirmar aprobación" }),
  );
  await waitFor(() => {
    expect(
      calls.some((call) => call.includes("/approvals/appr-1/approve")),
    ).toBe(true);
  });

  const results = await axe(container);
  expect(results.violations).toEqual([]);
});

test("los permisos permanecen cerrados hasta validar el dashboard", async () => {
  loginSession("provider_admin");
  mockApi(routesFor("provider_admin"));
  const regularFetch = globalThis.fetch;
  let resolveDashboard: (response: Response) => void = () => undefined;
  const pendingDashboard = new Promise<Response>((resolve) => {
    resolveDashboard = resolve;
  });
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) =>
    String(input).endsWith("/dashboard")
      ? pendingDashboard
      : regularFetch(input, init)) as typeof fetch;

  render(<App />);

  expect(screen.queryByRole("link", { name: "Aprobaciones" })).toBeNull();
  expect(
    screen.queryByRole("link", { name: "Usuarios y permisos" }),
  ).toBeNull();

  resolveDashboard(
    new Response(JSON.stringify(dashboardBody("provider_admin")), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  expect(
    await screen.findByRole("link", { name: "Usuarios y permisos" }),
  ).toBeTruthy();
});

test("un operador no recibe la capacidad administrativa de aprobar", async () => {
  loginSession("commercial");
  const calls = mockApi(routesFor("commercial"));
  render(<App />);

  await waitForDashboard();
  expect(screen.queryByRole("link", { name: "Aprobaciones" })).toBeNull();
  expect(calls.some((call) => call.includes("/approvals"))).toBe(false);
});

test("la importación de producto valida primero y usa idempotencia al confirmar", async () => {
  loginSession("provider_admin");
  mockApi(routesFor("provider_admin"));
  const regularFetch = globalThis.fetch;
  const importRequests: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/api/bridge/import/products")) {
      importRequests.push({ url, init });
      const body = JSON.parse(String(init?.body)) as { dry_run: boolean };
      return new Response(
        JSON.stringify(
          body.dry_run
            ? {
                status: "dry_run",
                valid_rows: 1,
                invalid_rows: 0,
                errors: [],
              }
            : { status: "success", imported_count: 1, errors: [] },
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    return regularFetch(input, init);
  }) as typeof fetch;
  render(<App />);

  await userEvent.click(await screen.findByRole("link", { name: "Productos" }));
  const importForm = screen.getByRole("form", { name: "Importar producto" });
  const importFields = within(importForm);
  await userEvent.type(importFields.getByLabelText("SKU"), "SKU-PROD-1");
  await userEvent.type(
    importFields.getByLabelText("Nombre"),
    "Producto auditado",
  );
  await userEvent.clear(importFields.getByLabelText("Precio unitario"));
  await userEvent.type(importFields.getByLabelText("Precio unitario"), "25.50");
  await userEvent.clear(importFields.getByLabelText("Stock"));
  await userEvent.type(importFields.getByLabelText("Stock"), "4");
  await userEvent.click(
    screen.getByRole("button", { name: "Validar producto" }),
  );

  expect(
    await screen.findByText(
      "Validación correcta. Revisa los datos antes de confirmar.",
    ),
  ).toBeTruthy();
  expect(importRequests).toHaveLength(1);
  const previewBody = JSON.parse(String(importRequests[0].init?.body)) as {
    dry_run: boolean;
    items: Array<Record<string, unknown>>;
  };
  expect(previewBody.dry_run).toBe(true);
  expect(previewBody.items[0]).not.toHaveProperty("tax_rate");

  await userEvent.click(
    screen.getByRole("button", { name: "Confirmar importación" }),
  );
  expect(
    await screen.findByText("Producto importado correctamente (1)."),
  ).toBeTruthy();
  expect(importRequests).toHaveLength(2);
  const commitBody = JSON.parse(String(importRequests[1].init?.body)) as {
    dry_run: boolean;
  };
  expect(commitBody.dry_run).toBe(false);
  expect(
    new Headers(importRequests[1].init?.headers).get("Idempotency-Key"),
  ).toMatch(/^portal-product-/);
});

test("una sesión revocada se cierra sin conservar permisos", async () => {
  loginSession("provider_admin");
  mockApi({
    ...routesFor("provider_admin"),
    "/dashboard": {
      status: 401,
      body: { detail: "La sesión ha sido revocada" },
    },
  });
  render(<App />);

  expect(
    await screen.findByRole("heading", { name: "Plataforma de agentes IA" }),
  ).toBeTruthy();
  expect(sessionStorage.getItem("agent_token")).toBeNull();
  expect(
    screen.getByText(
      "Tu sesión ha caducado o ha sido revocada. Vuelve a identificarte.",
    ),
  ).toBeTruthy();
});

test("el portal oculta registros con origen de prueba", async () => {
  loginSession("viewer");
  mockApi({
    ...routesFor("viewer"),
    "/catalog/products": {
      status: 200,
      body: {
        items: [
          {
            id: "prod-real",
            sku: "REAL-1",
            name: "Producto operativo",
            category: "Industrial",
            unit_price: 10,
            tax_rate: 0.21,
            available_stock: 2,
            source: "local",
            created_at: "2026-08-15T08:00:00",
            updated_at: "2026-08-15T08:00:00",
          },
          {
            id: "prod-demo",
            sku: "DEMO-1",
            name: "Producto semilla",
            category: "Pruebas",
            unit_price: 1,
            tax_rate: 0.21,
            available_stock: 99,
            source: "demo_seed",
            created_at: "2026-08-15T08:00:00",
            updated_at: "2026-08-15T08:00:00",
          },
        ],
        total: 2,
        limit: 50,
        offset: 0,
      },
    },
  });
  render(<App />);

  await userEvent.click(await screen.findByRole("link", { name: "Productos" }));
  expect(await screen.findByText("Producto operativo")).toBeTruthy();
  expect(screen.queryByText("Producto semilla")).toBeNull();
  expect(
    screen.getByText(/Se han ocultado 1 registros con origen de prueba/),
  ).toBeTruthy();
});

test("el catálogo pagina y muestra la frescura de cada fila", async () => {
  loginSession("provider_admin");
  const calls = mockApi({
    ...routesFor("provider_admin"),
    "/catalog/products": {
      status: 200,
      body: {
        items: [
          {
            id: "prod-1",
            sku: "SKU-1",
            name: "Producto reciente",
            category: "Industrial",
            unit_price: 10,
            tax_rate: 0.21,
            available_stock: 5,
            source: "local",
            created_at: "2026-08-15T08:00:00",
            updated_at: "2026-08-15T08:00:00",
          },
          {
            id: "prod-2",
            sku: "SKU-2",
            name: "Producto antiguo",
            category: "Oficina",
            unit_price: 20,
            tax_rate: 0.21,
            available_stock: 2,
            source: "prestashop",
            created_at: "2026-01-01T08:00:00",
            updated_at: "2026-01-01T08:00:00",
          },
        ],
        total: 2,
        limit: 50,
        offset: 0,
      },
    },
  });
  render(<App />);

  await waitForDashboard();
  await userEvent.click(screen.getByRole("link", { name: "Productos" }));
  expect(await screen.findByText("Producto reciente")).toBeTruthy();
  expect(screen.getByText("Producto antiguo")).toBeTruthy();
  // Resumen de paginación y controles visibles.
  expect(screen.getByText(/Mostrando 1–2 de 2 productos/)).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Página anterior",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    (
      screen.getByRole("button", {
        name: "Página siguiente",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.getByRole("combobox", { name: "Filtrar catálogo por origen" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("combobox", { name: "Ordenar catálogo por" }),
  ).toBeTruthy();
  // La petición usa el envelope paginado con orden estable por defecto.
  expect(
    calls.some((call) =>
      call.includes("/catalog/products?limit=50&offset=0&sort=name&order=asc"),
    ),
  ).toBe(true);
});

test("el catálogo busca y pagina cuando hay más de una página", async () => {
  loginSession("provider_admin");
  const calls = mockApi({
    ...routesFor("provider_admin"),
    "/catalog/products": {
      status: 200,
      body: {
        items: [
          {
            id: "prod-1",
            sku: "SKU-1",
            name: "Acuarela Jovi",
            category: "Bellas artes",
            unit_price: 3.77,
            tax_rate: 0.21,
            available_stock: 5000,
            source: "prestashop",
            created_at: "2026-08-15T08:00:00",
            updated_at: "2026-08-15T08:00:00",
          },
        ],
        total: 51,
        limit: 50,
        offset: 0,
      },
    },
  });
  render(<App />);

  await waitForDashboard();
  await userEvent.click(screen.getByRole("link", { name: "Productos" }));
  await userEvent.type(
    await screen.findByLabelText("Buscar en el catálogo"),
    "acuarela",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Buscar en catálogo" }),
  );

  expect(await screen.findByText("Acuarela Jovi")).toBeTruthy();
  expect(screen.getByText(/Mostrando 1–1 de 51 productos/)).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Página siguiente",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
  expect(
    calls.some((call) =>
      call.includes("/catalog/products?query=acuarela&limit=50&offset=0"),
    ),
  ).toBe(true);

  await userEvent.click(
    screen.getByRole("button", { name: "Página siguiente" }),
  );
  expect(
    calls.some((call) =>
      call.includes("/catalog/products?query=acuarela&limit=50&offset=50"),
    ),
  ).toBe(true);
});

test("el panel de aprobaciones permite ejecutar la ronda de agentes (propuestas)", async () => {
  loginSession("provider_admin");
  const calls = mockApi({
    ...routesFor("provider_admin"),
    "/approvals?status_filter=pending": { status: 200, body: [] },
    "/agent-proposals/run": {
      status: 200,
      body: {
        proposed: 2,
        by_agent: { crm_agent: 1, social_agent: 1 },
        proposals: [
          {
            id: "prop-1",
            action_type: "agent_proposal:create_follow_up",
            target_key: "lead-1",
            requested_by: "crm_agent",
            rationale: "Mensaje social urgente",
          },
          {
            id: "prop-2",
            action_type: "agent_proposal:dismiss_message",
            target_key: "msg-2",
            requested_by: "social_agent",
            rationale: "Spam",
          },
        ],
      },
    },
  });
  render(<App />);

  await userEvent.click(
    await screen.findByRole("link", { name: "Aprobaciones" }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Ejecutar agentes" }),
  );

  await waitFor(() => {
    expect(calls.some((call) => call.includes("/agent-proposals/run"))).toBe(
      true,
    );
  });
  expect(
    await screen.findByText(
      /Propuestas creadas: 1 de crm_agent, 1 de social_agent/,
    ),
  ).toBeTruthy();
});

test("el admin cambia el color de acento de la instalación", async () => {
  loginSession("provider_admin");
  const calls = mockApi({
    ...routesFor("provider_admin"),
    "/appearance/settings": {
      status: 200,
      body: { accent_color: "#246bfd", updated_by: null },
    },
  });
  render(<App />);
  await waitForDashboard();

  await userEvent.click(
    await screen.findByRole("link", { name: "Usuarios y permisos" }),
  );
  expect(
    await screen.findByRole("heading", {
      name: "Color de acento de la instalación",
    }),
  ).toBeTruthy();

  await userEvent.click(
    screen.getByRole("button", { name: "Usar acento #7c5cf0" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Guardar acento" }));

  await waitFor(() => {
    expect(
      calls.some(
        (call) =>
          call.startsWith("PUT ") && call.includes("/appearance/settings"),
      ),
    ).toBe(true);
  });
  expect(
    await screen.findByText(/actualizado para toda la instalación/),
  ).toBeTruthy();
  expect(document.documentElement.style.getPropertyValue("--accent")).toBe(
    "#7c5cf0",
  );
  // Limpieza: no contaminar el CSS global de otros tests
  document.documentElement.style.removeProperty("--accent");
  document.documentElement.style.removeProperty("--accent-soft");
  localStorage.removeItem("accent");
});

test("el toggle de densidad alterna entre cómodo y compacto", async () => {
  loginSession("provider_admin");
  mockApi({
    ...routesFor("provider_admin"),
    "/appearance/settings": {
      status: 200,
      body: { accent_color: "#246bfd", updated_by: null },
    },
  });
  render(<App />);
  await waitForDashboard();

  expect(document.documentElement.dataset.density).toBe("comfortable");
  const toggle = screen.getByRole("button", {
    name: "Activar modo compacto",
  });
  expect(toggle.getAttribute("aria-pressed")).toBe("false");

  await userEvent.click(toggle);
  expect(document.documentElement.dataset.density).toBe("compact");
  expect(localStorage.getItem("density")).toBe("compact");
  expect(
    screen
      .getByRole("button", { name: "Activar modo compacto" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  expect(
    screen
      .getByRole("button", { name: "Activar modo cómodo" })
      .getAttribute("aria-pressed"),
  ).toBe("false");

  await userEvent.click(
    screen.getByRole("button", { name: "Activar modo cómodo" }),
  );
  expect(document.documentElement.dataset.density).toBe("comfortable");
  expect(localStorage.getItem("density")).toBe("comfortable");
  localStorage.removeItem("density");
  delete document.documentElement.dataset.density;
});

test("el segmented de tema alterna entre claro y oscuro", async () => {
  loginSession("provider_admin");
  mockApi({
    ...routesFor("provider_admin"),
    "/appearance/settings": {
      status: 200,
      body: { accent_color: "#246bfd", updated_by: null },
    },
  });
  render(<App />);
  await waitForDashboard();

  expect(document.documentElement.dataset.theme).toBe("light");
  const oscuro = screen.getByRole("button", { name: "Activar tema oscuro" });
  expect(oscuro.getAttribute("aria-pressed")).toBe("false");
  expect(
    screen
      .getByRole("button", { name: "Activar tema claro" })
      .getAttribute("aria-pressed"),
  ).toBe("true");

  await userEvent.click(oscuro);
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("theme")).toBe("dark");
  expect(oscuro.getAttribute("aria-pressed")).toBe("true");
  expect(
    screen
      .getByRole("button", { name: "Activar tema claro" })
      .getAttribute("aria-pressed"),
  ).toBe("false");

  await userEvent.click(
    screen.getByRole("button", { name: "Activar tema claro" }),
  );
  expect(document.documentElement.dataset.theme).toBe("light");
  localStorage.removeItem("theme");
  delete document.documentElement.dataset.theme;
});
