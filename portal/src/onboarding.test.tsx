/**
 * Onboarding guiado (T-072): primer acceso para personas sin experiencia.
 *
 * - Sin preferencia guardada: al cargar el dashboard se abre el asistente
 *   paso a paso y la barra lateral solo muestra Asistente y Resumen.
 * - Las 3 preguntas de ejemplo se envían al chat universal real (/ceo/chat).
 * - «Mostrar todos los módulos» persiste el estado y revela la navegación
 *   completa (según RBAC); «Seguir en modo guiado» cierra el overlay pero
 *   mantiene ocultos los módulos.
 * - Con la preferencia «done» el onboarding no vuelve a aparecer.
 * - Accesible (axe) y sin diálogos anidados bloqueantes tras terminar.
 */
import { beforeEach, expect, test } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import App from "./App";
import {
  ONBOARDING_EXAMPLE_QUESTIONS,
  ONBOARDING_STORAGE_KEY,
} from "./onboarding";

type MockResponse = { status: number; body: unknown };

function mockApi(routes: Record<string, MockResponse>) {
  const calls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push(`${method} ${url}`);
    for (const [suffix, response] of Object.entries(routes)) {
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

function loginSession() {
  sessionStorage.setItem("agent_token", "token-test");
  sessionStorage.setItem("agent_user", "admin");
  sessionStorage.setItem("agent_role", "provider_admin");
  sessionStorage.setItem("agent_must_change", "false");
}

function dashboardBody() {
  return {
    installation_id: "test-installation",
    installed_version: "0.9.1",
    pilot_mode: false,
    role: "provider_admin",
    permissions: {
      approve: true,
      manage_leads: true,
      manage_users: true,
      view_costs: true,
      import_catalog: true,
    },
    integrations: { prestashop: "not_configured" },
    counts: { products: 2, customers: 1, quotes: 1, orders: 0 },
  };
}

function routesFor() {
  return {
    "/dashboard": { status: 200, body: dashboardBody() },
    "/costs": {
      status: 200,
      body: {
        total_executions: 0,
        total_tokens_consumed: 0,
        total_estimated_cost_usd: 0,
        avg_latency_ms: 0,
        simulated_executions: 0,
      },
    },
    "/integrations/prestashop/sync/history?limit=8": {
      status: 200,
      body: { history: [] },
    },
    "/approvals?status_filter=pending": { status: 200, body: [] },
    "/catalog/products": {
      status: 200,
      body: { items: [], total: 0, limit: 50, offset: 0 },
    },
    "/rag/documents": { status: 200, body: { documents: [] } },
    "/agents": { status: 200, body: { status: "success", agents: [] } },
    "/customers?limit=100": { status: 200, body: { items: [] } },
    "/quotes?limit=100": { status: 200, body: { items: [] } },
    "/orders?limit=100": { status: 200, body: { items: [] } },
    "/invoices?limit=100": { status: 200, body: { items: [] } },
    "/wiki/pages": { status: 200, body: { items: [] } },
    "/seo/projects": { status: 200, body: { items: [] } },
    "/landing-pages": { status: 200, body: { items: [] } },
    "/scheduled-tasks": { status: 200, body: { items: [] } },
    "/leads": { status: 200, body: [] },
    "/users": { status: 200, body: [] },
    "/ceo/chat": {
      status: 200,
      body: {
        answer: "Respuesta de ejemplo del asistente.",
        intent: "sales_summary",
        intent_label: "resumen de ventas",
        provider: "ollama",
        proposals: [],
      },
    },
  };
}

async function waitForOnboarding() {
  await waitFor(() => {
    expect(
      screen.getByRole("dialog", { name: /Tu empresa, en una conversación/ }),
    ).toBeTruthy();
  });
}

beforeEach(() => {
  window.localStorage.removeItem(ONBOARDING_STORAGE_KEY);
  // Estos tests se centran en el flujo de primeros pasos: el modo avanzado
  // queda activo para que «Mostrar todos los módulos» revele la navegación
  // completa (según RBAC). El comportamiento por defecto (modo simple) se
  // cubre en el test dedicado al final de este fichero.
  window.localStorage.setItem("advanced-mode", "on");
});

test("el primer acceso abre el onboarding y oculta el resto de módulos", async () => {
  loginSession();
  const calls = mockApi(routesFor());
  const { container } = render(<App />);

  await waitForOnboarding();

  // Solo Asistente y Resumen visibles mientras el modo guiado está activo.
  const labels = Array.from(container.querySelectorAll("nav a")).map(
    (link) => link.textContent,
  );
  expect(labels).toEqual(["Asistente", "Hoy"]);
  expect(screen.queryByRole("link", { name: "Productos" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Clientes" })).toBeNull();

  // El botón de salida del modo guiado está disponible en la barra lateral.
  expect(
    screen.getByRole("button", { name: "Mostrar todos los módulos" }),
  ).toBeTruthy();
  // El chat del Asistente se cargó detrás del overlay.
  expect(calls.some((call) => call.includes("/ceo/chat"))).toBe(false); // todavía no se ha enviado nada
});

test("las preguntas de ejemplo se envían al chat real del asistente", async () => {
  loginSession();
  const calls = mockApi(routesFor());
  render(<App />);

  await waitForOnboarding();
  await userEvent.click(screen.getByRole("button", { name: "Siguiente" }));

  // Las 3 preguntas de ejemplo aparecen en el paso 2 (dentro del diálogo;
  // el chat de la landing también muestra sugerencias con el mismo texto).
  const dialog = screen.getByRole("dialog", { name: /Pruébalo ahora mismo/ });
  for (const question of ONBOARDING_EXAMPLE_QUESTIONS) {
    expect(within(dialog).getByRole("button", { name: question })).toBeTruthy();
  }

  await userEvent.click(
    within(dialog).getByRole("button", {
      name: ONBOARDING_EXAMPLE_QUESTIONS[0],
    }),
  );

  // La pregunta se envió al backend y el paso 3 confirma la respuesta en el chat.
  await waitFor(() => {
    expect(
      calls.some(
        (call) => call.startsWith("POST") && call.includes("/ceo/chat"),
      ),
    ).toBe(true);
  });
  expect(
    screen.getByRole("dialog", { name: /La respuesta ya está en el chat/ }),
  ).toBeTruthy();
  // El mensaje del usuario quedó visible en el chat de la landing (puede
  // haber varias coincidencias: el mensaje, la sugerencia del chat…).
  expect(
    screen.getAllByText(ONBOARDING_EXAMPLE_QUESTIONS[0]).length,
  ).toBeGreaterThan(0);
});

test("«Mostrar todos los módulos» persiste y revela la navegación completa", async () => {
  loginSession();
  mockApi(routesFor());
  const { container } = render(<App />);

  await waitForOnboarding();
  await userEvent.click(
    screen.getByRole("button", { name: "Mostrar todos los módulos" }),
  );

  // El overlay desaparece, la preferencia queda persistida y la navegación
  // completa del admin vuelve a aparecer.
  await waitFor(() => {
    expect(
      screen.queryByRole("dialog", { name: /Tu empresa, en una conversación/ }),
    ).toBeNull();
  });
  expect(window.localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBe("done");
  const labels = Array.from(container.querySelectorAll("nav a")).map(
    (link) => link.textContent,
  );
  expect(labels).toContain("Productos");
  expect(labels).toContain("Clientes");
  expect(labels).toContain("Aprobaciones");
  expect(labels).toContain("Usuarios y permisos");
  expect(container.querySelectorAll('nav a[href^="#"]').length).toBe(14);
  expect(
    screen.queryByRole("button", { name: "Mostrar todos los módulos" }),
  ).toBeNull();
});

test("«Seguir en modo guiado» cierra el overlay pero mantiene ocultos los módulos", async () => {
  loginSession();
  mockApi(routesFor());
  const { container } = render(<App />);

  await waitForOnboarding();
  await userEvent.click(screen.getByRole("button", { name: "Siguiente" }));
  await userEvent.click(screen.getByRole("button", { name: "Continuar" }));
  await userEvent.click(
    screen.getByRole("button", { name: "Seguir en modo guiado" }),
  );

  await waitFor(() => {
    expect(
      screen.queryByRole("dialog", { name: /Tu empresa, en una conversación/ }),
    ).toBeNull();
  });
  // No se persiste como completado y los módulos siguen ocultos.
  expect(window.localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBeNull();
  expect(container.querySelectorAll('nav a[href^="#"]').length).toBe(2);
  // El botón de salida sigue disponible para cuando el usuario esté listo.
  expect(
    screen.getByRole("button", { name: "Mostrar todos los módulos" }),
  ).toBeTruthy();
});

test("el botón de la barra lateral revela los módulos sin pasar por el overlay", async () => {
  loginSession();
  mockApi(routesFor());
  render(<App />);

  await waitForOnboarding();
  await userEvent.click(
    screen.getByRole("button", { name: "Mostrar todos los módulos" }),
  );
  await waitFor(() => {
    expect(window.localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBe("done");
  });

  // Recarga simulada: con la preferencia guardada no vuelve a abrirse.
  const { container: second } = render(<App />);
  await waitFor(() => {
    expect(second.querySelectorAll('nav a[href^="#"]').length).toBe(14);
  });
  expect(
    screen.queryByRole("dialog", { name: /Tu empresa, en una conversación/ }),
  ).toBeNull();
});

test("con la preferencia completada el onboarding no aparece", async () => {
  window.localStorage.setItem(ONBOARDING_STORAGE_KEY, "done");
  loginSession();
  mockApi(routesFor());
  const { container } = render(<App />);

  await waitFor(() => {
    expect(container.querySelectorAll('nav a[href^="#"]').length).toBe(14);
  });
  expect(
    screen.queryByRole("dialog", { name: /Tu empresa, en una conversación/ }),
  ).toBeNull();
});

test("el overlay del onboarding es accesible (axe)", async () => {
  loginSession();
  mockApi(routesFor());
  const { container } = render(<App />);

  await waitForOnboarding();
  const results = await axe(container);
  expect(results.violations).toEqual([]);

  // El paso de ejemplos también es accesible.
  await userEvent.click(screen.getByRole("button", { name: "Siguiente" }));
  const resultsStep2 = await axe(container);
  expect(resultsStep2.violations).toEqual([]);
});

test("«Omitir» termina el onboarding y revela todos los módulos", async () => {
  loginSession();
  mockApi(routesFor());
  const { container } = render(<App />);

  await waitForOnboarding();
  await userEvent.click(screen.getByRole("button", { name: "Omitir" }));

  await waitFor(() => {
    expect(window.localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBe("done");
  });
  expect(container.querySelectorAll('nav a[href^="#"]').length).toBe(14);
});

test("tras completar el onboarding el modo simple queda activo por defecto", async () => {
  window.localStorage.removeItem("advanced-mode");
  loginSession();
  mockApi(routesFor());
  const { container } = render(<App />);

  await waitForOnboarding();
  await userEvent.click(
    screen.getByRole("button", { name: "Mostrar todos los módulos" }),
  );

  await waitFor(() => {
    expect(window.localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBe("done");
  });

  // El usuario ve lo esencial; los módulos técnicos esperan al modo avanzado.
  const labels = Array.from(container.querySelectorAll("nav a")).map(
    (link) => link.textContent,
  );
  expect(labels).toContain("Productos");
  expect(labels).toContain("Clientes");
  expect(labels).not.toContain("Webhooks salientes");
  expect(labels).not.toContain("Agentes de IA");
  // El toggle queda disponible para revelarlos cuando el usuario lo necesite.
  expect(
    screen.getByRole("button", { name: "Activar modo avanzado" }),
  ).toBeTruthy();
});
