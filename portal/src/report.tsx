import { useEffect, useState } from "react";
import { apiRequest } from "./api";

export type ReportStage = {
  key: string;
  name: string;
  position: number;
  count: number;
  total_value: number;
  aging_avg_days: number;
  aging_max_days: number;
};

export type SalesReportData = {
  stages: ReportStage[];
  summary: {
    total_opportunities: number;
    avg_ticket: number | null;
    median_ticket: number | null;
    open_count: number;
    open_value: number;
    won_count: number;
    lost_count: number;
    win_rate_pct: number | null;
    aging_avg_days: number | null;
    aging_max_days: number;
  };
};

function formatValue(value: number | null, currency = "EUR"): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(2)} ${currency}`;
}

function formatDays(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  if (value < 1) {
    const hours = Math.round(value * 24);
    if (hours <= 0) return "< 1 h";
    return hours === 1 ? "1 hora" : `${hours} horas`;
  }
  const rounded = Math.round(value);
  return rounded === 1 ? "1 día" : `${rounded} días`;
}

function KpiCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <article className="kpi-card">
      <span className="kpi-label">{label}</span>
      <strong className="kpi-value">{value}</strong>
      {hint && <span className="kpi-hint">{hint}</span>}
    </article>
  );
}

export function SalesReport({
  token,
  refreshRevision,
}: {
  token: string;
  refreshRevision: number;
}) {
  const [report, setReport] = useState<SalesReportData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    apiRequest<SalesReportData>("/pipeline/report", { token })
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error ? err.message : "No se pudo cargar el report",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [refreshRevision, token]);

  const summary = report?.summary;
  const maxCount = Math.max(1, ...(report?.stages.map((s) => s.count) ?? [1]));

  return (
    <section id="pipeline-report" className="panel" aria-label="Reporting de ventas">
      <div className="panel-heading">
        <div>
          <p>CRM local · P1-b</p>
          <h2>Reporting de ventas</h2>
        </div>
        <span className="counter">
          {summary?.total_opportunities ?? 0} oportunidades
        </span>
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {!error && report === null && (
        <div className="empty-state">Cargando report…</div>
      )}

      {!error && summary && (
        <>
          <div className="kpi-grid">
            <KpiCard
              label="Ticket medio"
              value={formatValue(summary.avg_ticket)}
            />
            <KpiCard
              label="Mediana"
              value={formatValue(summary.median_ticket)}
            />
            <KpiCard
              label="Win-rate"
              value={
                summary.win_rate_pct === null
                  ? "—"
                  : `${summary.win_rate_pct.toFixed(1)} %`
              }
              hint={`${summary.won_count} ganadas · ${summary.lost_count} perdidas`}
            />
            <KpiCard
              label="Pipeline abierto"
              value={formatValue(summary.open_value)}
              hint={`${summary.open_count} oportunidades`}
            />
            <KpiCard
              label="Aging medio"
              value={formatDays(summary.aging_avg_days)}
              hint={`máx ${formatDays(summary.aging_max_days)}`}
            />
          </div>

          <div className="report-funnel">
            <h3>Funnel por etapa</h3>
            {report.stages.length === 0 && (
              <div className="empty-state">Sin etapas configuradas.</div>
            )}
            {report.stages.length > 0 && (
              <ul className="funnel-list">
                {report.stages.map((stage) => (
                  <li key={stage.key} className="funnel-row">
                    <div className="funnel-meta">
                      <span className="funnel-name">{stage.name}</span>
                      <span className="funnel-count">
                        {stage.count} · {formatValue(stage.total_value)} · aging{" "}
                        {formatDays(stage.aging_avg_days)}
                        {stage.aging_max_days > stage.aging_avg_days
                          ? ` (máx ${formatDays(stage.aging_max_days)})`
                          : ""}
                      </span>
                    </div>
                    <div
                      className="funnel-bar"
                      role="img"
                      aria-label={`${stage.name}: ${stage.count} oportunidades, ${formatValue(stage.total_value)}`}
                    >
                      <div
                        className="funnel-fill"
                        style={{
                          width: `${Math.max(2, (stage.count / maxCount) * 100)}%`,
                        }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
