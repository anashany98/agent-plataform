import { expect, test } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CampaignsSection } from "./campaigns";

type CapturedRequest = {
  path: string;
  method: string;
  body?: unknown;
};

function requestPath(input: RequestInfo | URL): string {
  const url = new URL(String(input), "http://portal.test");
  return `${url.pathname}${url.search}`.replace(/^\/api\/bridge/, "");
}

const CAMPAIGN_FIXTURE = {
  id: "cmp-1",
  name: "Oferta septiembre",
  description: "Campaña de prueba",
  template_name: "Plantilla Demo",
  segment: { score_min: 20, sources: ["web"] },
  status: "draft",
  scheduled_at: null,
  sent_at: null,
  created_by: "admin",
  created_at: "2026-08-17T10:00:00",
  stats: {
    total: 0,
    sent: 0,
    failed: 0,
    skipped: 0,
    pending: 0,
    opened: 0,
    clicked: 0,
    bounced: 0,
    opened_rate: 0,
    clicked_rate: 0,
    bounce_rate: 0,
  },
};

const DETAIL_FIXTURE = {
  ...CAMPAIGN_FIXTURE,
  stats: {
    total: 2,
    sent: 2,
    failed: 0,
    skipped: 0,
    pending: 0,
    opened: 1,
    clicked: 1,
    bounced: 1,
    opened_rate: 50,
    clicked_rate: 50,
    bounce_rate: 50,
  },
  recipients: [
    {
      id: "rc-1",
      lead_id: "lead-1",
      email: "ana@example.invalid",
      first_name: "Ana",
      status: "sent",
      error: null,
      tracking_token: "tk-aaa",
      opened: true,
      clicked: true,
      bounced: false,
      sent_at: "2026-08-17T10:05:00",
    },
    {
      id: "rc-2",
      lead_id: "lead-2",
      email: "bruno@example.invalid",
      first_name: "Bruno",
      status: "sent",
      error: null,
      tracking_token: "tk-bbb",
      opened: false,
      clicked: false,
      bounced: true,
      sent_at: "2026-08-17T10:05:01",
    },
  ],
};

async function renderSection(
  captured: CapturedRequest[],
  { withTemplates = true }: { withTemplates?: boolean } = {},
) {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    captured.push({ path, method, body: init?.body });
    if (method === "POST" && path === "/campaigns") {
      return new Response(JSON.stringify(CAMPAIGN_FIXTURE), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (method === "GET" && /^\/campaigns\/[^/]+$/.test(path)) {
      return new Response(JSON.stringify(DETAIL_FIXTURE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (method === "POST" && /^\/campaigns\/[^/]+\/preview$/.test(path)) {
      return new Response(
        JSON.stringify({
          count: 3,
          sample: [{ id: "lead-1", first_name: "Ana" }],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (method === "POST" && /^\/campaigns\/[^/]+\/send$/.test(path)) {
      return new Response(
        JSON.stringify({
          ...CAMPAIGN_FIXTURE.stats,
          sent: 2,
          failed: 0,
          skipped: 0,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (path === "/campaigns") {
      return new Response(JSON.stringify({ campaigns: [CAMPAIGN_FIXTURE] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (path === "/email/templates") {
      return new Response(
        JSON.stringify({
          items: withTemplates
            ? [{ id: "tpl-1", name: "Plantilla Demo", subject: "x", body: "x" }]
            : [],
          variables: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    return new Response(JSON.stringify({ detail: "no encontrado" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  render(<CampaignsSection token="token-test" refreshRevision={0} />);
}

test("lista campañas con estadísticas", async () => {
  const captured: CapturedRequest[] = [];
  await renderSection(captured);
  await waitFor(() => {
    expect(screen.getByText("Oferta septiembre")).toBeTruthy();
  });
  expect(screen.getByText("Borrador")).toBeTruthy();
  expect(screen.getAllByText("0", { selector: "td" }).length).toBeGreaterThan(
    0,
  );
  expect(
    captured.some(
      (request) => request.path === "/campaigns" && request.method === "GET",
    ),
  ).toBe(true);
});

test("crea campaña enviando el segmento construido", async () => {
  const user = userEvent.setup();
  const captured: CapturedRequest[] = [];
  await renderSection(captured);
  await waitFor(() => {
    expect(screen.getByText("Nueva campaña")).toBeTruthy();
  });
  await user.type(
    screen.getByPlaceholderText("Ej.: Oferta septiembre logística"),
    "Oferta logística",
  );
  await user.selectOptions(
    screen.getByLabelText("Plantilla de email (activa)"),
    "Plantilla Demo",
  );
  await user.type(screen.getByLabelText("Score mínimo (0-100)"), "25");
  await user.click(screen.getByLabelText("Web"));
  await user.click(
    screen.getByRole("button", { name: "+ Criterio de campo personalizado" }),
  );
  await user.type(screen.getByLabelText("Clave del campo"), "sector");
  await user.selectOptions(screen.getByLabelText("Operador"), "eq");
  await user.type(screen.getByLabelText("Valor"), "logistica");
  await user.click(
    screen.getByRole("button", { name: "Crear campaña (borrador)" }),
  );

  await waitFor(() => {
    const post = captured.find(
      (request) => request.method === "POST" && request.path === "/campaigns",
    );
    expect(post).toBeTruthy();
  });
  const post = captured.find(
    (request) => request.method === "POST" && request.path === "/campaigns",
  )!;
  const body = JSON.parse(String(post.body)) as {
    name: string;
    segment: { score_min: number; sources: string[]; custom_fields: unknown[] };
  };
  expect(body.name).toBe("Oferta logística");
  expect(body.segment.score_min).toBe(25);
  expect(body.segment.sources).toEqual(["web"]);
  expect(body.segment.custom_fields).toEqual([
    { key: "sector", op: "eq", value: "logistica" },
  ]);
});

test("detalle muestra destinatarios con apertura y clic", async () => {
  const user = userEvent.setup();
  const captured: CapturedRequest[] = [];
  await renderSection(captured);
  await waitFor(() => {
    expect(screen.getByText("Oferta septiembre")).toBeTruthy();
  });
  await user.click(screen.getByRole("button", { name: "Detalle" }));
  await waitFor(() => {
    expect(screen.getByText("ana@example.invalid")).toBeTruthy();
  });
  expect(screen.getByText("bruno@example.invalid")).toBeTruthy();
  // Estadísticas derivadas del tracking en la ficha
  expect(screen.getByText("Abiertos 1")).toBeTruthy();
  expect(screen.getByText("Clics 1")).toBeTruthy();
  expect(screen.getByText("Rebotados 1")).toBeTruthy();
  // Resumen de entregabilidad con tasas (el <strong> parte el texto: se
  // verifica el textContent del bloque completo).
  expect(screen.getByText("Entregabilidad")).toBeTruthy();
  const deliverability = screen.getByText("Entregabilidad").parentElement!;
  expect(deliverability.textContent).toContain("Tasa de apertura 50%");
  expect(deliverability.textContent).toContain("Tasa de clics 50%");
  expect(deliverability.textContent).toContain("Tasa de rebote 50%");
  expect(deliverability.textContent).toContain("Entregados 1 de 2");
  // Columna de rebote por destinatario
  expect(screen.getByRole("columnheader", { name: "Rebote" })).toBeTruthy();
  expect(
    captured.some((request) => /^\/campaigns\/cmp-1$/.test(request.path)),
  ).toBe(true);
});
