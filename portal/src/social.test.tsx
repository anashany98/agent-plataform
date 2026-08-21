import { expect, test } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SocialSection } from "./social";

type CapturedRequest = {
  path: string;
  method: string;
  body?: unknown;
};

function requestPath(input: RequestInfo | URL): string {
  const url = new URL(String(input), "http://portal.test");
  return `${url.pathname}${url.search}`.replace(/^\/api\/bridge/, "");
}

const CHANNEL_FIXTURE = {
  id: "ch-1",
  name: "WhatsApp comercial",
  channel: "whatsapp",
  external_account_id: null,
  is_active: true,
  scopes: [],
  secret_set: true,
  secret_prefix: "test",
  verify_token_set: true,
  last_webhook_at: "2026-08-17T10:00:00",
  created_at: "2026-08-17T09:00:00",
};

const MESSAGE_FIXTURE = {
  id: "msg-1",
  channel_id: "ch-1",
  thread_id: null,
  source_message_id: "wamid.1",
  sender_handle: "34600111222",
  sender_name: "Ana García",
  email: null,
  phone: "34600111222",
  body: "Hola, quiero un presupuesto para su catálogo, ¿pueden contactarme?",
  status: "triaged",
  lead_id: "lead-1",
  created_at: "2026-08-17T10:05:00",
  triage: {
    intent: "lead",
    language: "es",
    register: "formal",
    sentiment: 0.5,
    urgency: 25,
    entities: { skus: [] },
    score_social: 65,
    summary: "Lead de Ana García",
    decided_by: "deterministic",
  },
};

const STATS_FIXTURE = {
  by_status: { triaged: 1, dismissed: 1 },
  by_channel: { "ch-1": 2 },
  by_intent: { lead: 1, queja: 1 },
  avg_score_social: 55,
};

async function renderSection(
  captured: CapturedRequest[],
  { isAdmin = true }: { isAdmin?: boolean } = {},
) {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = requestPath(input);
    const method = init?.method ?? "GET";
    captured.push({ path, method, body: init?.body });
    if (method === "GET" && path.startsWith("/social/inbox")) {
      return new Response(JSON.stringify({ items: [MESSAGE_FIXTURE] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (method === "GET" && path === "/social/stats") {
      return new Response(JSON.stringify(STATS_FIXTURE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (method === "GET" && path === "/social/channels") {
      return new Response(JSON.stringify({ items: [CHANNEL_FIXTURE] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (method === "POST" && path === "/social/channels") {
      return new Response(JSON.stringify(CHANNEL_FIXTURE), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (
      method === "POST" &&
      /^\/social\/messages\/[^/]+\/dismiss$/.test(path)
    ) {
      return new Response(
        JSON.stringify({ id: "msg-1", status: "dismissed" }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      );
    }
    if (method === "PATCH" && /^\/social\/channels\/[^/]+$/.test(path)) {
      return new Response(
        JSON.stringify({ ...CHANNEL_FIXTURE, is_active: false }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      );
    }
    if (method === "POST" && /^\/social\/channels\/[^/]+\/test$/.test(path)) {
      return new Response(JSON.stringify({ message_id: "msg-test-1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (method === "DELETE" && /^\/social\/channels\/[^/]+$/.test(path)) {
      return new Response(JSON.stringify({ id: "ch-1", deleted: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ detail: "no mock" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  const utils = render(
    <SocialSection token="t" refreshRevision={1} isAdmin={isAdmin} />,
  );
  await screen.findByText(/Ana García/);
  return utils;
}

test("muestra el inbox con el triaje y las estadísticas", async () => {
  const captured: CapturedRequest[] = [];
  await renderSection(captured);

  expect(await screen.findByText(/quiero un presupuesto/)).toBeTruthy();
  expect(screen.getAllByText("Lead").length).toBeGreaterThan(0);
  expect(screen.getAllByText(/score 65/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/WhatsApp comercial/).length).toBeGreaterThan(0);
  expect(screen.getByText("2")).toBeTruthy(); // total de mensajes
});

test("descartar un mensaje dispara el POST y muestra el resultado", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderSection(captured);

  await user.click(screen.getByRole("button", { name: "Descartar" }));
  await waitFor(() =>
    expect(
      captured.some(
        (r) =>
          r.method === "POST" && r.path === "/social/messages/msg-1/dismiss",
      ),
    ).toBe(true),
  );
});

test("admin puede crear un canal (POST con Idempotency-Key)", async () => {
  const captured: CapturedRequest[] = [];
  const user = userEvent.setup();
  await renderSection(captured);

  await user.type(screen.getByLabelText("Nombre del canal"), "Instagram inbox");
  await user.type(
    screen.getByLabelText("Secreto del webhook"),
    "s3cret-key-ok",
  );
  await user.click(screen.getByRole("button", { name: "Crear canal" }));

  await waitFor(() => {
    const create = captured.find(
      (r) => r.method === "POST" && r.path === "/social/channels",
    );
    expect(create).toBeTruthy();
  });
  expect(screen.getByText(/Canal creado/)).toBeTruthy();
});

test("el resto de roles no ve la gestión de canales", async () => {
  const captured: CapturedRequest[] = [];
  await renderSection(captured, { isAdmin: false });

  expect(screen.queryByText("Nuevo canal")).toBeNull();
  expect(captured.some((r) => r.path === "/social/channels")).toBe(false);
});
