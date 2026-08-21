import { expect, test } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  AgentRegistrySection,
  CommerceSection,
  ContentGrowthSection,
  SchedulerSection,
} from "./productionModules";

type CapturedRequest = {
  path: string;
  method: string;
  init?: RequestInit;
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

test("ventas crea y confirma un presupuesto sin aceptar totales del cliente", async () => {
  const captured: CapturedRequest[] = [];
  const customer = {
    id: "cust-real",
    name: "Cliente Real",
    email: "real@example.invalid",
    phone: null,
    company: "Empresa",
    created_at: "2026-08-15T08:00:00",
  };
  const invoice = {
    id: "invoice-draft-1",
    invoice_number: null,
    order_id: "order-existing",
    customer_id: customer.id,
    items: [],
    total_amount: "12.10",
    currency: "EUR",
    status: "draft",
    created_at: "2026-08-15T08:00:00",
  };
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    captured.push({ path, method, init });
    if (method === "GET" && path === "/customers?limit=100") {
      return response({ items: [customer] });
    }
    if (method === "GET" && path === "/quotes?limit=100") {
      return response({ items: [] });
    }
    if (method === "GET" && path === "/orders?limit=100") {
      return response({ items: [] });
    }
    if (method === "GET" && path === "/invoices?limit=100") {
      return response({ items: [invoice] });
    }
    if (method === "POST" && path === "/quotes") {
      return response(
        {
          quote_id: "quote-real-1",
          confirmation_token: "0123456789abcdef0123456789abcdef",
          grand_total: 12.1,
          currency: "EUR",
        },
        201,
      );
    }
    if (method === "POST" && path === "/quotes/quote-real-1/confirm") {
      return response({
        order_id: "order-real-1",
        invoice_draft_id: "invoice-real-1",
        approval_id: "approval-real-1",
      });
    }
    if (
      method === "POST" &&
      path === "/invoices/invoice-draft-1/request-approval"
    ) {
      return response({ approval_id: "approval-invoice-1" });
    }
    return response({ detail: `Ruta no mockeada: ${method} ${path}` }, 500);
  }) as typeof fetch;

  const { container } = render(
    <CommerceSection token="token" refreshRevision={0} canWrite />,
  );
  expect(await screen.findByText("real@example.invalid")).toBeTruthy();

  await userEvent.selectOptions(screen.getByLabelText("Cliente"), customer.id);
  await userEvent.type(screen.getByLabelText("ID de producto"), "product-real");
  await userEvent.click(screen.getByRole("button", { name: "Crear borrador" }));

  expect(await screen.findByText(/Aún no es un pedido/)).toBeTruthy();
  expect(container.textContent).not.toContain(
    "0123456789abcdef0123456789abcdef",
  );
  const createCall = captured.find(
    (call) => call.method === "POST" && call.path === "/quotes",
  );
  expect(createCall).toBeTruthy();
  const quotePayload = JSON.parse(String(createCall?.init?.body)) as Record<
    string,
    unknown
  >;
  expect(quotePayload).toEqual({
    customer_id: customer.id,
    items: [{ product_id: "product-real", qty: 1 }],
  });
  expect(quotePayload).not.toHaveProperty("grand_total");
  expect(new Headers(createCall?.init?.headers).get("Idempotency-Key")).toMatch(
    /^portal-quote-create-/,
  );

  await userEvent.type(
    screen.getByLabelText("Escribe la referencia exacta"),
    "quote-real-1",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Confirmar y crear pedido" }),
  );
  await waitFor(() => {
    expect(
      captured.some(
        (call) =>
          call.method === "POST" &&
          call.path === "/quotes/quote-real-1/confirm",
      ),
    ).toBe(true);
  });
  const confirmCall = captured.find(
    (call) => call.path === "/quotes/quote-real-1/confirm",
  );
  expect(new Headers(confirmCall?.init?.headers).get("Idempotency-Key")).toBe(
    "portal-quote-confirm-quote-real-1",
  );
  expect(
    await screen.findByText(/factura invoice-real-1 pendiente/),
  ).toBeTruthy();

  await userEvent.click(
    screen.getByRole("button", { name: "Solicitar aprobación" }),
  );
  await waitFor(() => {
    expect(
      captured.some(
        (call) => call.path === "/invoices/invoice-draft-1/request-approval",
      ),
    ).toBe(true);
  });
  const invoiceCall = captured.find((call) =>
    call.path.includes("invoice-draft-1/request-approval"),
  );
  expect(new Headers(invoiceCall?.init?.headers).get("Idempotency-Key")).toBe(
    "portal-invoice-approval-invoice-draft-1",
  );
});

test("contenido usa versión e idempotencia y declara límites de publicación y SEO", async () => {
  const captured: CapturedRequest[] = [];
  const wikiPage = {
    id: "wiki-real-1",
    slug: "guia-real",
    title: "Guía real",
    content: "Contenido revisable",
    status: "draft",
    version: 3,
    updated_at: "2026-08-15T08:00:00",
    published_at: null,
  };
  const seoProject = {
    id: "seo-real-1",
    name: "SEO real",
    domain: "example.invalid",
    configuration: {},
    status: "draft",
    version: 2,
    updated_at: "2026-08-15T08:00:00",
    analysis_engine: "deterministic_html_static_v1",
    external_crawler: "not_implemented",
  };
  const landing = {
    id: "landing-real-1",
    slug: "oferta-real",
    title: "Oferta real",
    content: { headline: "Oferta", cta: "Contactar" },
    status: "draft",
    version: 4,
    updated_at: "2026-08-15T08:00:00",
    approved_at: null,
    render_engine: "deterministic_escaped_html_v1",
    external_publication: "not_implemented",
  };
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    captured.push({ path, method, init });
    if (method === "GET" && path === "/wiki/pages") {
      return response({ items: [wikiPage] });
    }
    if (method === "GET" && path === "/seo/projects") {
      return response({ items: [seoProject] });
    }
    if (method === "GET" && path === "/landing-pages") {
      return response({ items: [landing] });
    }
    if (method === "POST" && path.endsWith("/request-publication")) {
      return response({ approval_id: "approval-wiki" });
    }
    if (method === "POST" && path.endsWith("/request-approval")) {
      return response({ approval_id: "approval-landing" });
    }
    if (method === "POST" && path.endsWith("/analyze-html")) {
      return response({
        analysis_id: "analysis-real-1",
        result: {
          method: "deterministic_html_static_v1",
          external_fetch_performed: false,
          measured: {
            title: "Página real",
            h1_count: 1,
            images_total: 1,
            images_missing_alt: 1,
            links_total: 2,
          },
          recommendations: [
            {
              code: "images_missing_alt",
              priority: "high",
              action: "Añadir alt.",
            },
          ],
        },
      });
    }
    if (method === "POST" && path === "/wiki/pages") {
      return response({ ...wikiPage, id: "wiki-created", version: 1 }, 201);
    }
    return response({ detail: `Ruta no mockeada: ${method} ${path}` }, 500);
  }) as typeof fetch;

  render(<ContentGrowthSection token="token" refreshRevision={0} canWrite />);
  expect(await screen.findByText("Guía real")).toBeTruthy();
  expect(
    screen.getAllByText(/Publicación externa: no implementada/).length,
  ).toBeGreaterThan(0);

  const wikiPanel = screen
    .getByRole("heading", { name: "Wiki" })
    .closest("article");
  if (!wikiPanel) throw new Error("No se encontró el panel Wiki");
  await userEvent.click(
    within(wikiPanel).getByRole("button", {
      name: "Solicitar publicación interna",
    }),
  );
  const wikiApproval = await waitFor(() => {
    const call = captured.find((item) =>
      item.path.endsWith("/request-publication"),
    );
    expect(call).toBeTruthy();
    return call;
  });
  expect(new Headers(wikiApproval?.init?.headers).get("If-Match")).toBe("3");
  expect(new Headers(wikiApproval?.init?.headers).get("Idempotency-Key")).toBe(
    "portal-wiki-approval-wiki-real-1-v3",
  );

  await userEvent.type(within(wikiPanel).getByLabelText("Slug"), "nueva-guia");
  await userEvent.type(
    within(wikiPanel).getByLabelText("Título"),
    "Nueva guía",
  );
  await userEvent.type(
    within(wikiPanel).getByLabelText("Contenido"),
    "Contenido real",
  );
  await userEvent.click(
    within(wikiPanel).getByRole("button", { name: "Guardar borrador" }),
  );
  await waitFor(() => {
    expect(
      captured.some(
        (call) => call.method === "POST" && call.path === "/wiki/pages",
      ),
    ).toBe(true);
  });
  const wikiCreate = captured.find(
    (call) => call.method === "POST" && call.path === "/wiki/pages",
  );
  expect(new Headers(wikiCreate?.init?.headers).get("Idempotency-Key")).toMatch(
    /^portal-wiki-create-/,
  );

  const seoPanel = screen
    .getByRole("heading", { name: "SEO técnico" })
    .closest("article");
  if (!seoPanel) throw new Error("No se encontró el panel SEO");
  await userEvent.selectOptions(
    within(seoPanel).getByLabelText("Proyecto"),
    seoProject.id,
  );
  await userEvent.type(
    within(seoPanel).getByLabelText("HTML"),
    "<html><head><title>Página real</title></head><body><h1>Hola</h1></body></html>",
  );
  await userEvent.click(
    within(seoPanel).getByRole("button", {
      name: "Ejecutar análisis estático",
    }),
  );
  expect(await screen.findByText("Descarga externa: no")).toBeTruthy();
  const analysisCall = captured.find((call) =>
    call.path.endsWith("/analyze-html"),
  );
  expect(
    new Headers(analysisCall?.init?.headers).get("Idempotency-Key"),
  ).toMatch(/^portal-seo-html-analysis-/);

  const landingPanel = screen
    .getByRole("heading", { name: "Landing pages" })
    .closest("article");
  if (!landingPanel) throw new Error("No se encontró el panel Landing");
  await userEvent.click(
    within(landingPanel).getByRole("button", {
      name: "Solicitar aprobación",
    }),
  );
  const landingApproval = await waitFor(() => {
    const call = captured.find((item) =>
      item.path.endsWith("/request-approval"),
    );
    expect(call).toBeTruthy();
    return call;
  });
  expect(new Headers(landingApproval?.init?.headers).get("If-Match")).toBe("4");
});

test("el planificador crea borradores y solicita activación con versión", async () => {
  const captured: CapturedRequest[] = [];
  const task = {
    id: "task-real-1",
    name: "Barrido real",
    task_type: "automation_sweep",
    payload: {},
    interval_seconds: 3600,
    status: "draft",
    version: 2,
    next_run_at: null,
    last_run_at: null,
  };
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    captured.push({ path, method, init });
    if (method === "GET" && path === "/scheduled-tasks") {
      return response({ items: [task] });
    }
    if (method === "POST" && path.endsWith("/request-activation")) {
      return response({ approval_id: "approval-task" });
    }
    if (method === "POST" && path === "/scheduled-tasks") {
      return response({ ...task, id: "task-created", version: 1 }, 201);
    }
    return response({ detail: "Ruta no mockeada" }, 500);
  }) as typeof fetch;

  render(<SchedulerSection token="token" refreshRevision={0} canWrite />);
  expect(await screen.findByText("Barrido real")).toBeTruthy();
  await userEvent.click(
    screen.getByRole("button", { name: "Solicitar activación" }),
  );
  const activation = await waitFor(() => {
    const call = captured.find((item) =>
      item.path.endsWith("/request-activation"),
    );
    expect(call).toBeTruthy();
    return call;
  });
  expect(new Headers(activation?.init?.headers).get("If-Match")).toBe("2");
  expect(new Headers(activation?.init?.headers).get("Idempotency-Key")).toBe(
    "portal-scheduled-task-activation-task-real-1-v2",
  );

  await userEvent.type(screen.getByLabelText("Nombre"), "Nueva tarea real");
  await userEvent.click(
    screen.getByRole("button", { name: "Guardar borrador" }),
  );
  await waitFor(() => {
    expect(
      captured.some(
        (call) => call.method === "POST" && call.path === "/scheduled-tasks",
      ),
    ).toBe(true);
  });
  const createCall = captured.find(
    (call) => call.method === "POST" && call.path === "/scheduled-tasks",
  );
  expect(new Headers(createCall?.init?.headers).get("Idempotency-Key")).toMatch(
    /^portal-scheduled-task-create-/,
  );
  expect(JSON.parse(String(createCall?.init?.body))).toMatchObject({
    task_type: "automation_sweep",
    interval_seconds: 3600,
  });
});

test("el registro de agentes persiste drafts y usa If-Match al activar", async () => {
  const captured: CapturedRequest[] = [];
  const agent = {
    agent_id: "custom_real",
    name: "Agente real",
    purpose: "Operación asistida",
    prompt: "Usa solo herramientas autorizadas.",
    autonomy_level: "Fase_D_Venta_Asistida",
    allowed_tools: ["search_products"],
    primary_model: "standard",
    fallback_model: "local",
    monthly_budget_usd: 5,
    status: "draft",
    version: 5,
    persisted: true,
  };
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    captured.push({ path, method, init });
    if (method === "GET" && path === "/agents") {
      return response({ status: "success", agents: [agent] });
    }
    if (method === "POST" && path.endsWith("/request-activation")) {
      return response({ approval_id: "approval-agent" });
    }
    if (method === "POST" && path === "/agents") {
      return response({
        status: "success",
        agent: { ...agent, agent_id: "nuevo_real", version: 1 },
      });
    }
    return response({ detail: "Ruta no mockeada" }, 500);
  }) as typeof fetch;

  render(<AgentRegistrySection token="token" refreshRevision={0} canWrite />);
  expect(await screen.findByText("Agente real")).toBeTruthy();
  await userEvent.click(
    screen.getByRole("button", { name: "Solicitar activación" }),
  );
  const activation = await waitFor(() => {
    const call = captured.find((item) =>
      item.path.endsWith("/request-activation"),
    );
    expect(call).toBeTruthy();
    return call;
  });
  expect(new Headers(activation?.init?.headers).get("If-Match")).toBe("5");
  expect(new Headers(activation?.init?.headers).get("Idempotency-Key")).toBe(
    "portal-agent-activation-custom_real-v5",
  );

  // El formulario de creación está plegado por defecto (modo simple): se abre
  // solo quien necesita la configuración avanzada.
  await userEvent.click(
    screen.getByText("Crear nuevo agente (configuración avanzada)"),
  );
  await userEvent.type(screen.getByLabelText("ID del agente"), "nuevo_real");
  await userEvent.type(screen.getByLabelText("Nombre"), "Nuevo agente");
  await userEvent.type(screen.getByLabelText("Propósito"), "Ayuda operativa");
  await userEvent.type(
    screen.getByLabelText("Instrucción del sistema"),
    "Usa herramientas permitidas.",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Guardar borrador" }),
  );
  await waitFor(() => {
    expect(
      captured.some(
        (call) => call.method === "POST" && call.path === "/agents",
      ),
    ).toBe(true);
  });
  const createCall = captured.find(
    (call) => call.method === "POST" && call.path === "/agents",
  );
  expect(new Headers(createCall?.init?.headers).get("Idempotency-Key")).toMatch(
    /^portal-agent-create-/,
  );
  expect(JSON.parse(String(createCall?.init?.body))).toMatchObject({
    agent_id: "nuevo_real",
    status: "draft",
    allowed_tools: ["search_products"],
  });
});

test("el registro muestra agentes especializados con su módulo y alcance", async () => {
  const moduleAgent = {
    agent_id: "crm_agent",
    name: "Agente de clientes (CRM)",
    purpose: "Gestionar el CRM: leads, oportunidades, actividades y pipeline",
    autonomy_level: "L0_Respuesta_Limitada",
    allowed_tools: ["list_leads", "list_activities", "get_pipeline_report"],
    monthly_budget_usd: 12,
    status: "active",
    module: "crm",
    module_label: "Clientes (CRM)",
    scope: "leads, oportunidades, pipeline, actividades y calendario",
  };
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    if (method === "GET" && path === "/agents") {
      return response({ status: "success", agents: [moduleAgent] });
    }
    if (method === "GET" && path === "/agents/supervision") {
      return response({ status: "success", agents: [] });
    }
    return response({ detail: "Ruta no mockeada" }, 500);
  }) as typeof fetch;

  render(<AgentRegistrySection token="token" refreshRevision={0} canWrite />);
  expect(await screen.findByText("Agente de clientes (CRM)")).toBeTruthy();
  expect(screen.getByText("Clientes (CRM)")).toBeTruthy();
  expect(
    screen.getByText(/Alcance: leads, oportunidades, pipeline, actividades y calendario/),
  ).toBeTruthy();
  expect(screen.getByText(/list_leads, list_activities, get_pipeline_report/)).toBeTruthy();
});

test("el panel de supervisión muestra módulo, estado de tools y actuaciones auditadas", async () => {
  const moduleAgent = {
    agent_id: "crm_agent",
    name: "Agente de clientes (CRM)",
    purpose: "Gestionar el CRM",
    autonomy_level: "L0_Respuesta_Limitada",
    allowed_tools: ["list_leads", "list_activities", "get_pipeline_report"],
    monthly_budget_usd: 12,
    status: "active",
    module: "crm",
    module_label: "Clientes (CRM)",
    scope: "leads, oportunidades, pipeline",
  };
  const supervisionAgent = {
    agent_id: "crm_agent",
    name: "Agente de clientes (CRM)",
    module: "crm",
    module_label: "Clientes (CRM)",
    scope: "leads, oportunidades, pipeline, actividades y calendario",
    autonomy_level: "L0_Respuesta_Limitada",
    status: "active",
    persisted: false,
    allowed_tools: ["list_leads", "list_activities", "get_pipeline_report"],
    authorized_tools: ["list_activities", "list_leads", "get_pipeline_report"],
    tools: [
      {
        name: "list_leads",
        kind: "read",
        declared: true,
        authorized: true,
        calls: 4,
        success: 3,
        denied: 1,
        errors: 0,
        last_status: "success",
        last_at: "2026-08-17T09:00:00",
      },
      {
        name: "list_activities",
        kind: "read",
        declared: true,
        authorized: true,
        calls: 1,
        success: 1,
        denied: 0,
        errors: 0,
        last_status: "success",
        last_at: "2026-08-17T08:30:00",
      },
      {
        name: "get_pipeline_report",
        kind: "read",
        declared: true,
        authorized: true,
        calls: 0,
        success: 0,
        denied: 0,
        errors: 0,
        last_status: null,
        last_at: null,
      },
    ],
    summary: {
      calls: 5,
      success: 4,
      denied: 1,
      errors: 0,
      last_activity_at: "2026-08-17T09:00:00",
    },
    recent_actions: [
      {
        timestamp: "2026-08-17T09:00:00",
        tool: "list_leads",
        status: "success",
        detail: null,
      },
      {
        timestamp: "2026-08-17T08:59:00",
        tool: "list_leads",
        status: "denied",
        detail: "fuera de la allowlist del agente",
      },
    ],
  };
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    if (method === "GET" && path === "/agents") {
      return response({ status: "success", agents: [moduleAgent] });
    }
    if (method === "GET" && path === "/agents/supervision") {
      return response({ status: "success", agents: [supervisionAgent] });
    }
    if (method === "GET" && path === "/agents/autonomy") {
      return response({
        default_mode: "manual",
        agents: [
          {
            agent_id: "crm_agent",
            name: "Agente de clientes (CRM)",
            module_label: "Clientes (CRM)",
            autonomy_level: "L0_Respuesta_Limitada",
            mode: "autonomous",
            max_value_threshold: 500,
            allow_follow_ups: true,
            allow_spam_dismissals: false,
            notify_on_deviation_only: false,
          },
        ],
      });
    }
    if (method === "GET" && path.startsWith("/agents/digest")) {
      return response({
        window_days: 7,
        total_decisions: 2,
        by_agent: [
          {
            agent_id: "crm_agent",
            agent_label: "el agente de clientes (CRM)",
            total: 1,
            deviations: 0,
            reverted: 0,
            deviations_only: false,
          },
        ],
        pending_human_approvals: 2,
        decisions: [
          {
            id: "dec-1",
            agent_id: "crm_agent",
            agent_label: "el agente de clientes (CRM)",
            action_type: "agent_proposal:create_follow_up",
            action_label: "crear un seguimiento",
            target_key: "lead-abc",
            target_kind: "lead",
            target_focus_id: "lead-abc",
            target_label: "María Urgente",
            executed_at: "2026-08-17T09:00:00",
            deviation: false,
            deviation_reason: null,
            reverted: false,
            reverted_by: null,
            reverted_at: null,
          },
          {
            id: "dec-2",
            agent_id: "finance_agent",
            agent_label: "el agente financiero",
            action_type: "issue_invoice",
            action_label: "emitir una factura",
            target_key: "inv-e2e-0001",
            target_kind: "invoice",
            target_focus_id: "inv-e2e-0001",
            target_label: "Acme E2E (INV-2026-E2E-ABCDEF)",
            executed_at: "2026-08-17T10:00:00",
            deviation: false,
            deviation_reason: null,
            reverted: false,
            reverted_by: null,
            reverted_at: null,
          },
        ],
      });
    }
    return response({ detail: "Ruta no mockeada" }, 500);
  }) as typeof fetch;

  render(<AgentRegistrySection token="token" refreshRevision={0} canWrite />);
  expect(
    await screen.findByRole("heading", { name: "Supervisión por módulo" }),
  ).toBeTruthy();
  expect(screen.getAllByText("Control empresarial").length).toBeGreaterThan(0);
  expect(
    await screen.findByRole("heading", { name: "Autonomía por excepción" }),
  ).toBeTruthy();
  expect(
    await screen.findByRole("heading", {
      name: "Digest de decisiones de los agentes",
    }),
  ).toBeTruthy();
  expect(screen.getByText("2 decisiones auto-ejecutadas")).toBeTruthy();
  expect(screen.getByText("2 pendientes de aprobación humana")).toBeTruthy();
  // El digest de la supervisión usa los labels en lenguaje llano del chat
  // (el agente aparece en el resumen por agente y en la tabla de decisiones).
  expect(screen.getAllByText("el agente de clientes (CRM)").length).toBeGreaterThan(0);
  expect(screen.getByText("crear un seguimiento")).toBeTruthy();
  // El objetivo humanizado enlaza a la ficha del lead en Clientes: guarda
  // el id a enfocar en sessionStorage y navega al hash del módulo.
  const targetLink = await screen.findByRole("link", { name: "María Urgente" });
  expect(targetLink.getAttribute("href")).toBe("#clientes");
  expect(targetLink.getAttribute("title")).toBe("Abrir el lead en Clientes");
  await userEvent.click(targetLink);
  expect(window.location.hash).toBe("#clientes");
  expect(sessionStorage.getItem("portal_clientes_focus")).toBe("lead-abc");
  // La factura humanizada enlaza a la ficha en Ventas (mismo contrato
  // target_kind/target_focus_id que valida la E2E backend).
  const invoiceLink = await screen.findByRole("link", {
    name: "Acme E2E (INV-2026-E2E-ABCDEF)",
  });
  expect(invoiceLink.getAttribute("href")).toBe("#ventas");
  expect(invoiceLink.getAttribute("title")).toBe("Abrir la factura en Ventas");
  await userEvent.click(invoiceLink);
  expect(window.location.hash).toBe("#ventas");
  expect(sessionStorage.getItem("portal_ventas_focus")).toBe("inv-e2e-0001");
  expect(screen.getByText("Guardar autonomía")).toBeTruthy();
  // Dos decisiones en el fixture → dos filas con su botón de revertir.
  expect(screen.getAllByText("Revertir").length).toBe(2);
  expect(screen.getByText("5 llamadas")).toBeTruthy();
  expect(screen.getByText("3 tools autorizadas")).toBeTruthy();
  expect(screen.getAllByText("autorizada").length).toBeGreaterThan(0);
  expect(screen.getAllByText("read").length).toBeGreaterThan(0);
  expect(screen.getByText(/fuera de la allowlist del agente/)).toBeTruthy();
  expect(screen.getByText("sin uso")).toBeTruthy();
});
