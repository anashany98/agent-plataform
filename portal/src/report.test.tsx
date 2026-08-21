import { expect, test } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { SalesReport, SalesReportData } from "./report";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function reportFixture(): SalesReportData {
  return {
    stages: [
      {
        key: "new",
        name: "Nuevo",
        position: 0,
        count: 2,
        total_value: 400,
        aging_avg_days: 6.5,
        aging_max_days: 10,
      },
      {
        key: "won",
        name: "Ganado",
        position: 1,
        count: 1,
        total_value: 400,
        aging_avg_days: 0,
        aging_max_days: 0,
      },
    ],
    summary: {
      total_opportunities: 4,
      avg_ticket: 212.5,
      median_ticket: 200,
      open_count: 2,
      open_value: 400,
      won_count: 1,
      lost_count: 1,
      win_rate_pct: 50,
      aging_avg_days: 4.2,
      aging_max_days: 10,
    },
  };
}

async function renderReport(data: SalesReportData = reportFixture()) {
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://portal.test");
    if (url.pathname.replace(/^\/api\/bridge/, "") === "/pipeline/report") {
      return response(data);
    }
    return response({}, 404);
  }) as typeof fetch;

  render(<SalesReport token="token-test" refreshRevision={1} />);
  await screen.findByRole("heading", { name: "Reporting de ventas" });
}

test("el report muestra los KPIs y el funnel por etapa", async () => {
  await renderReport();
  expect(screen.getByText("Ticket medio")).toBeTruthy();
  expect(screen.getByText("212.50 EUR")).toBeTruthy();
  expect(screen.getByText("Mediana")).toBeTruthy();
  expect(screen.getByText("200.00 EUR")).toBeTruthy();
  expect(screen.getByText("Win-rate")).toBeTruthy();
  expect(screen.getByText("50.0 %")).toBeTruthy();
  expect(screen.getByText("1 ganadas · 1 perdidas")).toBeTruthy();
  expect(screen.getByText("Pipeline abierto")).toBeTruthy();
  expect(screen.getByText("400.00 EUR")).toBeTruthy();
  expect(screen.getByText("Aging medio")).toBeTruthy();
  expect(screen.getByText("4 días")).toBeTruthy();
  expect(screen.getByText("máx 10 días")).toBeTruthy();

  // Funnel: filas por etapa con recuento, valor y aging.
  expect(screen.getByText("Funnel por etapa")).toBeTruthy();
  expect(screen.getByText(/^Nuevo$/)).toBeTruthy();
  expect(
    screen.getByText((content, element) => {
      const isCount =
        element !== null && element.classList.contains("funnel-count");
      return (
        isCount &&
        content.includes("2") &&
        content.includes("400.00 EUR") &&
        content.includes("7 días") &&
        content.includes("máx 10 días")
      );
    }),
  ).toBeTruthy();
});

test("el aging sub-diario se muestra en horas, no como 0 días", async () => {
  const data = reportFixture();
  data.summary.aging_avg_days = 0.38;
  data.summary.aging_max_days = 0.55;
  data.stages[0].aging_avg_days = 0.38;
  data.stages[0].aging_max_days = 0.55;
  await renderReport(data);
  expect(screen.getByText("9 horas")).toBeTruthy();
  expect(screen.getByText("máx 13 horas")).toBeTruthy();
  expect(
    screen.getByText((content, element) => {
      const isCount =
        element !== null && element.classList.contains("funnel-count");
      return isCount && content.includes("9 horas") && content.includes("máx 13 horas");
    }),
  ).toBeTruthy();
});

test("el report sin datos muestra guiones y el estado vacío del funnel", async () => {
  await renderReport({
    stages: [],
    summary: {
      total_opportunities: 0,
      avg_ticket: null,
      median_ticket: null,
      open_count: 0,
      open_value: 0,
      won_count: 0,
      lost_count: 0,
      win_rate_pct: null,
      aging_avg_days: null,
      aging_max_days: 0,
    },
  });
  expect(screen.getAllByText("0 oportunidades").length).toBeGreaterThan(0);
  expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  expect(screen.getByText("Sin etapas configuradas.")).toBeTruthy();
});

test("el report muestra el error si la API falla", async () => {
  globalThis.fetch = (async () =>
    response({ detail: "No tienes permiso para realizar esta operación." }, 403)) as typeof fetch;

  render(<SalesReport token="token-test" refreshRevision={1} />);
  await waitFor(() => {
    expect(
      screen.getByText("No tienes permiso para realizar esta operación."),
    ).toBeTruthy();
  });
});
