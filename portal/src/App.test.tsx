/**
 * Evals D-027: portal sin anclas rotas, con estados reales y accesible.
 *
 * - Cada enlace de la navegación apunta a una sección renderizada (D-027:
 *   "cinco anchors sin destino").
 * - El login y el panel pasan el chequeo de accesibilidad (axe).
 * - Las secciones muestran estados vacío/error explícitos, nunca datos
 *   simulados presentados como reales.
 */
import { expect, test } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'vitest-axe';
import App from './App';

type MockResponse = { status: number; body: unknown };

function mockApi(routes: Record<string, MockResponse>) {
  const calls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    calls.push(`${method} ${url}`);
    for (const [suffix, response] of Object.entries(routes)) {
      if (url.endsWith(suffix)) {
        return new Response(JSON.stringify(response.body), {
          status: response.status,
          headers: { 'Content-Type': 'application/json' },
        });
      }
    }
    return new Response(JSON.stringify({ detail: 'Ruta no mockeada' }), { status: 500 });
  }) as typeof fetch;
  return calls;
}

function loginSession() {
  sessionStorage.setItem('agent_token', 'token-test');
  sessionStorage.setItem('agent_user', 'admin');
  sessionStorage.setItem('agent_must_change', 'false');
}

const DASHBOARD_ROUTES = {
  '/provider/dashboard': {
    status: 200,
    body: {
      installation_id: 'test-installation',
      installed_version: '0.9.1',
      pilot_mode: false,
      integrations: { prestashop: 'not_configured', activepieces: 'not_configured' },
      counts: { products: 2, customers: 1, orders: 0, pending_approvals: 1 },
    },
  },
  '/costs': {
    status: 200,
    body: {
      total_executions: 0,
      total_tokens_consumed: 0,
      total_estimated_cost_usd: 0,
      avg_latency_ms: 0,
      simulated_executions: 0,
    },
  },
  '/approvals?status_filter=pending': { status: 200, body: [] },
  '/tools/products': {
    status: 200,
    body: [
      {
        id: 'prod-1',
        sku: 'SKU-0001',
        name: 'Producto real',
        category: 'Industrial',
        unit_price: 10,
        tax_rate: 0.21,
        available_stock: 5,
        source: 'local',
      },
    ],
  },
  '/rag/documents': {
    status: 200,
    body: { documents: [{ id: 'doc-1', file_name: 'manual.txt', mime_type: 'text/plain', classification: 'internal', dlp_findings: [], created_at: '2026-08-03T10:00:00' }] },
  },
  '/agents': {
    status: 200,
    body: { status: 'success', agents: [{ agent_id: 'sales_agent', name: 'Agente comercial', purpose: 'Recomendación de productos' }] },
  },
  '/users': {
    status: 200,
    body: [{ id: 'u1', username: 'admin', role: 'provider_admin', is_active: true, must_change_password: false }],
  },
};

test('el login es accesible y muestra errores del servidor', async () => {
  mockApi({ '/auth/login': { status: 401, body: { detail: 'Credenciales inválidas' } } });
  const { container } = render(<App />);

  expect(await screen.findByRole('heading', { name: 'Plataforma de agentes IA' })).toBeTruthy();
  const results = await axe(container);
  expect(results.violations).toEqual([]);

  await userEvent.type(screen.getByLabelText('Contraseña'), 'una-password-invalida');
  await userEvent.click(screen.getByRole('button', { name: 'Acceder' }));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByRole('alert').textContent).toContain('Credenciales inválidas');
});

test('cada enlace de navegación apunta a una sección renderizada', async () => {
  loginSession();
  mockApi(DASHBOARD_ROUTES);
  const { container } = render(<App />);

  await waitFor(() => {
    expect(screen.getAllByText('Resumen operativo').length).toBeGreaterThan(0);
  });

  const links = Array.from(container.querySelectorAll('nav a[href^="#"]'));
  expect(links.length).toBe(7);
  for (const link of links) {
    const targetId = (link.getAttribute('href') ?? '').slice(1);
    const target = container.querySelector(`#${targetId}`);
    expect(target, `El ancla ${targetId} debe tener una sección de destino`).not.toBeNull();
  }
});

test('la navegación muestra secciones con datos reales y estados vacíos', async () => {
  loginSession();
  mockApi(DASHBOARD_ROUTES);
  const { container } = render(<App />);

  await waitFor(() => {
    expect(container.querySelector('#catalogo tbody tr')).not.toBeNull();
  });
  expect(screen.getByText('Producto real')).toBeTruthy();

  await userEvent.click(screen.getByRole('link', { name: 'Documentos' }));
  await waitFor(() => {
    expect(screen.getByText('manual.txt')).toBeTruthy();
  });

  await userEvent.click(screen.getByRole('link', { name: 'Agentes de IA' }));
  await waitFor(() => {
    expect(screen.getByText('Agente comercial')).toBeTruthy();
  });

  await userEvent.click(screen.getByRole('link', { name: 'Usuarios y permisos' }));
  await waitFor(() => {
    expect(screen.getByText('provider_admin')).toBeTruthy();
  });

  await userEvent.click(screen.getByRole('link', { name: 'Automatizaciones' }));
  expect(
    screen.getByText(/El diseñador de automatizaciones no forma parte de la candidata core/i),
  ).toBeTruthy();
});

test('los módulos muestran estado de error explícito cuando la API falla', async () => {
  loginSession();
  mockApi({
    ...DASHBOARD_ROUTES,
    '/users': { status: 403, body: { detail: 'Permisos insuficientes' } },
  });
  render(<App />);

  await userEvent.click(await screen.findByRole('link', { name: 'Usuarios y permisos' }));
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toContain('Permisos insuficientes');
  expect(alert.textContent).toContain('rol administrador');
});

test('las aprobaciones pendientes permiten decidir y el panel es accesible', async () => {
  loginSession();
  const calls = mockApi({
    ...DASHBOARD_ROUTES,
    '/approvals?status_filter=pending': {
      status: 200,
      body: [
        {
          id: 'appr-1',
          action_type: 'issue_invoice',
          target_key: 'INV-001',
          status: 'pending',
          payload: {},
          created_at: '2026-08-03T10:00:00',
        },
      ],
    },
    '/approvals/appr-1/approve': { status: 200, body: { status: 'approved' } },
  });
  const { container } = render(<App />);

  await userEvent.click(await screen.findByRole('link', { name: 'Aprobaciones' }));
  expect(await screen.findByText('Aprobar borrador de factura')).toBeTruthy();

  await userEvent.click(screen.getByRole('button', { name: 'Aprobar' }));
  await waitFor(() => {
    expect(calls.some((call) => call.includes('/approvals/appr-1/approve'))).toBe(true);
  });

  const results = await axe(container);
  expect(results.violations).toEqual([]);
});
