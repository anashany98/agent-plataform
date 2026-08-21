/**
 * Sección Clientes: leads y oportunidades, pipeline kanban, reporting, tareas,
 * calendario, cuentas, campos personalizados, campañas y escucha social.
 *
 * Extraída de `App.tsx`; la navegación interna por pestañas vive aquí y delega
 * en los módulos específicos (kanban, report, calendar, …).
 */

import { FormEvent, useEffect, useState } from "react";
import { API_BASE } from "../api";
import { api } from "../apiHelpers";
import {
  formatDate,
  formatNumber,
  isDemoSource,
  tryFocusRow,
} from "../appFormat";
import type { LeadRow } from "../appTypes";
import { ActivitiesSection } from "../activities";
import { AccountsSection } from "../accounts";
import { CalendarSection } from "../calendar";
import { CustomFieldsSection } from "../customFields";
import { CampaignsSection } from "../campaigns";
import { SocialSection } from "../social";
import { KanbanSection } from "../kanban";
import { SalesReport } from "../report";

export function LeadsSection({
  token,
  refreshRevision,
  active = true,
}: {
  token: string;
  refreshRevision: number;
  active?: boolean;
}) {
  const [rows, setRows] = useState<LeadRow[] | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    email: "",
    first_name: "",
    phone: "",
    company_name: "",
  });
  const [creating, setCreating] = useState(false);
  const [createResult, setCreateResult] = useState("");
  const [createError, setCreateError] = useState("");
  const visibleRows = rows?.filter((row) => !isDemoSource(row.source)) ?? null;
  const blockedDemoCount = rows ? rows.length - (visibleRows?.length ?? 0) : 0;

  async function loadLeads() {
    setError("");
    try {
      setRows(await api<LeadRow[]>("/leads", token));
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudieron cargar los leads",
      );
    }
  }

  useEffect(() => {
    void loadLeads();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshRevision, token]);

  // Deep-link desde el digest de agentes: enfoca y resalta el lead objetivo.
  // La sección vive en un div oculto y no se desmonta al cambiar de pestaña,
  // por eso `active` también dispara el reintento (no solo los cambios de
  // `rows`): la clave se pone antes de navegar a #clientes.
  useEffect(() => {
    if (!active) return;
    if (
      tryFocusRow(
        "portal_clientes_focus",
        (id) => `[data-focus-id="${CSS.escape(id)}"]`,
      )
    ) {
      return;
    }
    const timer = window.setTimeout(() => {
      sessionStorage.removeItem("portal_clientes_focus");
    }, 5_000);
    return () => window.clearTimeout(timer);
  }, [active, rows]);

  async function createLead(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setCreateResult("");
    setCreateError("");
    try {
      await api("/leads", token, {
        method: "POST",
        body: JSON.stringify({
          email: form.email.trim(),
          first_name: form.first_name.trim(),
          phone: form.phone.trim() || null,
          company_name: form.company_name.trim() || null,
        }),
      });
      setCreateResult("Lead creado");
      setForm({ email: "", first_name: "", phone: "", company_name: "" });
      await loadLeads();
    } catch (err) {
      setCreateError(
        err instanceof Error ? err.message : "No se pudo crear el lead",
      );
    } finally {
      setCreating(false);
    }
  }

  const [exporting, setExporting] = useState(false);

  async function exportCsv() {
    setExporting(true);
    setCreateError("");
    try {
      const response = await fetch(`${API_BASE}/leads/export.csv`, {
        headers: { Authorization: `Bearer ${token}`, Accept: "text/csv" },
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error("No se pudo exportar el CSV de leads");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "leads.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setCreateError(
        err instanceof Error ? err.message : "No se pudo exportar el CSV",
      );
    } finally {
      setExporting(false);
    }
  }

  return (
    <section
      id="clientes"
      className="panel"
      aria-label="Clientes y oportunidades"
    >
      <div className="panel-heading">
        <div>
          <p>CRM local</p>
          <h2>Leads y oportunidades</h2>
        </div>
        <div className="kanban-actions">
          <span className="counter">{visibleRows?.length ?? 0}</span>
          <button
            type="button"
            className="secondary-button"
            disabled={exporting || (visibleRows?.length ?? 0) === 0}
            onClick={() => void exportCsv()}
          >
            {exporting ? "Exportando…" : "Exportar CSV"}
          </button>
        </div>
      </div>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {!error && rows === null && (
        <div className="empty-state">Cargando leads…</div>
      )}
      {!error && blockedDemoCount > 0 && (
        <div className="alert warning" role="status">
          Se han ocultado {blockedDemoCount} leads con origen de prueba.
        </div>
      )}
      {!error && visibleRows !== null && visibleRows.length === 0 && (
        <div className="empty-state">
          No hay leads en esta instalación. Crea el primero con el formulario.
        </div>
      )}
      {!error && visibleRows !== null && visibleRows.length > 0 && (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Leads y oportunidades</caption>
            <thead>
              <tr>
                <th scope="col">Cliente</th>
                <th scope="col">Email</th>
                <th scope="col">Oportunidades</th>
                <th scope="col">Estado</th>
                <th scope="col">Alta</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((lead) => (
                <tr key={lead.id} data-focus-id={lead.id}>
                  <td>
                    {lead.first_name}
                    {lead.company_name ? ` (${lead.company_name})` : ""}
                  </td>
                  <td>{lead.email}</td>
                  <td>
                    {lead.opportunities.length === 0
                      ? "—"
                      : lead.opportunities
                          .map(
                            (opp) =>
                              `${opp.name} · ${formatNumber(opp.monetary_value)} ${opp.currency}`,
                          )
                          .join(" / ")}
                  </td>
                  <td>{lead.status}</td>
                  <td>{formatDate(lead.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form
        className="import-form"
        onSubmit={(event) => void createLead(event)}
        aria-label="Nuevo lead"
        aria-busy={creating}
      >
        <p>Nuevo lead</p>
        <div className="import-grid">
          <label>
            Email
            <input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              required
            />
          </label>
          <label>
            Nombre
            <input
              value={form.first_name}
              onChange={(e) => setForm({ ...form, first_name: e.target.value })}
              required
            />
          </label>
          <label>
            Teléfono
            <input
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
            />
          </label>
          <label>
            Empresa
            <input
              value={form.company_name}
              onChange={(e) =>
                setForm({ ...form, company_name: e.target.value })
              }
            />
          </label>
          <button type="submit" className="primary-button" disabled={creating}>
            {creating ? "Creando…" : "Crear lead"}
          </button>
        </div>
        {createError && (
          <div className="alert error" role="alert">
            {createError}
          </div>
        )}
        {createResult && (
          <div className="alert info" role="status">
            {createResult}
          </div>
        )}
      </form>
    </section>
  );
}

export function ClientesSection({
  token,
  isAdmin,
  refreshRevision,
  active,
}: {
  token: string;
  isAdmin: boolean;
  refreshRevision: number;
  active: boolean;
}) {
  const [view, setView] = useState<
    | "tabla"
    | "kanban"
    | "report"
    | "activities"
    | "calendar"
    | "accounts"
    | "campos"
    | "campanas"
    | "social"
  >("tabla");

  // Deep-link desde la pantalla «Hoy»: la tarjeta guarda la pestaña deseada
  // (campanas | social) en sessionStorage y navega a #clientes. Se consume
  // en cada activación de la sección (la primera visita y las siguientes) y
  // se limpia para que una visita normal arranque en «Leads y oportunidades».
  useEffect(() => {
    if (!active) return;
    const tab = sessionStorage.getItem("portal_clientes_tab");
    sessionStorage.removeItem("portal_clientes_tab");
    if (tab === "campanas" || tab === "social") {
      setView(tab);
      return;
    }
    // Deep-link del digest: el lead objetivo vive en la vista «tabla».
    if (sessionStorage.getItem("portal_clientes_focus")) {
      setView("tabla");
    }
  }, [active]);

  return (
    <div className="clientes-section">
      <div className="segmented" role="tablist" aria-label="Vista de clientes">
        <button
          type="button"
          role="tab"
          aria-selected={view === "tabla"}
          className={view === "tabla" ? "active" : ""}
          onClick={() => setView("tabla")}
        >
          Leads y oportunidades
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "kanban"}
          className={view === "kanban" ? "active" : ""}
          onClick={() => setView("kanban")}
        >
          Pipeline (kanban)
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "report"}
          className={view === "report" ? "active" : ""}
          onClick={() => setView("report")}
        >
          Reporting de ventas
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "activities"}
          className={view === "activities" ? "active" : ""}
          onClick={() => setView("activities")}
        >
          Tareas
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "calendar"}
          className={view === "calendar" ? "active" : ""}
          onClick={() => setView("calendar")}
        >
          Calendario
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "accounts"}
          className={view === "accounts" ? "active" : ""}
          onClick={() => setView("accounts")}
        >
          Cuentas
        </button>
        {isAdmin && (
          <button
            type="button"
            role="tab"
            aria-selected={view === "campos"}
            className={view === "campos" ? "active" : ""}
            onClick={() => setView("campos")}
          >
            Campos personalizados
          </button>
        )}
        {isAdmin && (
          <button
            type="button"
            role="tab"
            aria-selected={view === "campanas"}
            className={view === "campanas" ? "active" : ""}
            onClick={() => setView("campanas")}
          >
            Campañas
          </button>
        )}
        <button
          type="button"
          role="tab"
          aria-selected={view === "social"}
          className={view === "social" ? "active" : ""}
          onClick={() => setView("social")}
        >
          Escucha social
        </button>
      </div>
      {view === "tabla" ? (
        <LeadsSection
          token={token}
          refreshRevision={refreshRevision}
          active={active}
        />
      ) : view === "kanban" ? (
        <KanbanSection
          token={token}
          isAdmin={isAdmin}
          refreshRevision={refreshRevision}
        />
      ) : view === "report" ? (
        <SalesReport token={token} refreshRevision={refreshRevision} />
      ) : view === "calendar" ? (
        <CalendarSection token={token} refreshRevision={refreshRevision} />
      ) : view === "accounts" ? (
        <AccountsSection token={token} refreshRevision={refreshRevision} />
      ) : view === "campos" ? (
        <CustomFieldsSection token={token} refreshRevision={refreshRevision} />
      ) : view === "campanas" ? (
        <CampaignsSection token={token} refreshRevision={refreshRevision} />
      ) : view === "social" ? (
        <SocialSection
          token={token}
          refreshRevision={refreshRevision}
          isAdmin={isAdmin}
        />
      ) : (
        <ActivitiesSection token={token} refreshRevision={refreshRevision} />
      )}
    </div>
  );
}
