import { FormEvent, useEffect, useState } from "react";
import { apiRequest } from "./api";

export type AccountRow = {
  id: string;
  name: string;
  industry: string | null;
  website: string | null;
  phone: string | null;
  city: string | null;
  country: string | null;
  notes: string | null;
  is_active: boolean;
  contact_count: number;
  open_value: number;
  open_count: number;
  won_value: number;
  lost_value: number;
  created_at: string | null;
  updated_at: string | null;
};

export type ContactRow = {
  id: string;
  account_id: string | null;
  full_name: string;
  email: string;
  phone: string | null;
  job_title: string | null;
  is_primary: boolean;
  merged_into_contact_id: string | null;
  lead_count: number;
  created_at: string | null;
};

type AccountOpportunity = {
  id: string;
  name: string;
  stage: string;
  status: string;
  monetary_value: number;
  currency: string;
  probability: number | null;
  created_at: string | null;
};

export type AccountDetail = AccountRow & {
  contacts: ContactRow[];
  opportunities: AccountOpportunity[];
};

function formatValue(value: number, currency: string): string {
  return `${Number.isFinite(value) ? value.toFixed(2) : "—"} ${currency}`;
}

function formatWhen(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("es-ES", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export function AccountsSection({
  token,
  refreshRevision,
}: {
  token: string;
  refreshRevision: number;
}) {
  const [rows, setRows] = useState<AccountRow[] | null>(null);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<AccountDetail | null>(null);
  const [, setLoadingDetail] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: "",
    industry: "",
    city: "",
    country: "",
    website: "",
    phone: "",
    notes: "",
  });
  const [contactForm, setContactForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    job_title: "",
    phone: "",
    is_primary: false,
  });

  async function load() {
    setError("");
    try {
      setRows(await apiRequest<AccountRow[]>("/accounts", { token }));
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "No se pudieron cargar las cuentas",
      );
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, refreshRevision]);

  async function createAccount(event: FormEvent) {
    event.preventDefault();
    if (!form.name.trim()) return;
    setError("");
    setSaving(true);
    try {
      await apiRequest<AccountRow>("/accounts", {
        token,
        method: "POST",
        body: JSON.stringify({
          name: form.name.trim(),
          industry: form.industry.trim() || null,
          city: form.city.trim() || null,
          country: form.country.trim() || null,
          website: form.website.trim() || null,
          phone: form.phone.trim() || null,
          notes: form.notes.trim() || null,
        }),
      });
      setForm({
        name: "",
        industry: "",
        city: "",
        country: "",
        website: "",
        phone: "",
        notes: "",
      });
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudo crear la cuenta",
      );
    } finally {
      setSaving(false);
    }
  }

  async function openDetail(accountId: string) {
    if (detail?.id === accountId) {
      setDetail(null);
      return;
    }
    setError("");
    setLoadingDetail(true);
    try {
      setDetail(
        await apiRequest<AccountDetail>(`/accounts/${accountId}`, { token }),
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudo cargar la cuenta",
      );
    } finally {
      setLoadingDetail(false);
    }
  }

  async function createContact(event: FormEvent) {
    event.preventDefault();
    if (
      !detail ||
      !contactForm.first_name.trim() ||
      !contactForm.email.trim()
    ) {
      return;
    }
    setError("");
    setSaving(true);
    try {
      await apiRequest<ContactRow>("/contacts", {
        token,
        method: "POST",
        body: JSON.stringify({
          account_id: detail.id,
          first_name: contactForm.first_name.trim(),
          last_name: contactForm.last_name.trim() || null,
          email: contactForm.email.trim(),
          job_title: contactForm.job_title.trim() || null,
          phone: contactForm.phone.trim() || null,
          is_primary: contactForm.is_primary,
        }),
      });
      setContactForm({
        first_name: "",
        last_name: "",
        email: "",
        job_title: "",
        phone: "",
        is_primary: false,
      });
      if (detail) {
        setDetail(
          await apiRequest<AccountDetail>(`/accounts/${detail.id}`, { token }),
        );
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudo crear el contacto",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="accounts-section" aria-label="Cuentas">
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {rows === null && !error && (
        <div className="empty-state">Cargando cuentas…</div>
      )}
      {rows !== null && (
        <>
          <div className="accounts-toolbar">
            <span className="counter">{rows.length} cuentas</span>
            <button
              type="button"
              className="secondary-button"
              onClick={() => void load()}
            >
              Actualizar
            </button>
          </div>
          <div className="table-wrap">
            <table>
              <caption className="sr-only">Cuentas (empresas)</caption>
              <thead>
                <tr>
                  <th scope="col">Cuenta</th>
                  <th scope="col">Sector</th>
                  <th scope="col">Ciudad</th>
                  <th scope="col">Contactos</th>
                  <th scope="col">Pipeline abierto</th>
                  <th scope="col">Ganado</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((account) => (
                  <AccountRowView
                    key={account.id}
                    account={account}
                    onToggle={() => void openDetail(account.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
          {detail && (
            <div className="account-detail panel">
              <h4>{detail.name}</h4>
              <p className="muted-text">
                {detail.industry ?? "Sin sector"} · {detail.city ?? "—"} ·{" "}
                {detail.website ?? "—"} · {detail.phone ?? "—"}
              </p>
              <div className="account-metrics">
                <span className="pill pill-neutral">
                  {detail.contacts.length} contactos
                </span>
                <span className="pill pill-blue">
                  {detail.open_count} abiertas ·{" "}
                  {formatValue(detail.open_value, "EUR")}
                </span>
                <span className="pill pill-green">
                  Ganado {formatValue(detail.won_value, "EUR")}
                </span>
                <span className="pill pill-red">
                  Perdido {formatValue(detail.lost_value, "EUR")}
                </span>
              </div>

              <h5>Contactos</h5>
              {detail.contacts.length === 0 && (
                <p className="muted-text">Sin contactos todavía.</p>
              )}
              {detail.contacts.map((contact) => (
                <div key={contact.id} className="contact-row">
                  <strong>
                    {contact.full_name || contact.email}
                    {contact.is_primary ? " ⭐" : ""}
                  </strong>
                  <span className="muted-text">
                    {contact.job_title ?? "—"} · {contact.email} ·{" "}
                    {contact.phone ?? "—"} · {contact.lead_count} leads
                  </span>
                </div>
              ))}
              <form
                className="contact-form"
                onSubmit={(event) => void createContact(event)}
              >
                <input
                  aria-label="Nombre del contacto"
                  placeholder="Nombre*"
                  value={contactForm.first_name}
                  onChange={(e) =>
                    setContactForm({
                      ...contactForm,
                      first_name: e.target.value,
                    })
                  }
                />
                <input
                  aria-label="Apellido del contacto"
                  placeholder="Apellidos"
                  value={contactForm.last_name}
                  onChange={(e) =>
                    setContactForm({
                      ...contactForm,
                      last_name: e.target.value,
                    })
                  }
                />
                <input
                  aria-label="Email del contacto"
                  placeholder="Email*"
                  type="email"
                  value={contactForm.email}
                  onChange={(e) =>
                    setContactForm({ ...contactForm, email: e.target.value })
                  }
                />
                <input
                  aria-label="Cargo del contacto"
                  placeholder="Cargo"
                  value={contactForm.job_title}
                  onChange={(e) =>
                    setContactForm({
                      ...contactForm,
                      job_title: e.target.value,
                    })
                  }
                />
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={contactForm.is_primary}
                    onChange={(e) =>
                      setContactForm({
                        ...contactForm,
                        is_primary: e.target.checked,
                      })
                    }
                  />
                  Principal
                </label>
                <button
                  type="submit"
                  className="primary-button"
                  disabled={saving}
                >
                  {saving ? "Guardando…" : "Añadir contacto"}
                </button>
              </form>

              <h5>Oportunidades</h5>
              {detail.opportunities.length === 0 && (
                <p className="muted-text">Sin oportunidades.</p>
              )}
              {detail.opportunities.map((opp) => (
                <div key={opp.id} className="contact-row">
                  <strong>{opp.name}</strong>
                  <span className="muted-text">
                    {formatValue(opp.monetary_value, opp.currency)} · etapa{" "}
                    {opp.stage} ·{" "}
                    {opp.probability !== null && opp.probability !== undefined
                      ? `${opp.probability}%`
                      : "prob. de etapa"}{" "}
                    · {formatWhen(opp.created_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
      <form
        className="account-form"
        onSubmit={(event) => void createAccount(event)}
      >
        <p>Nueva cuenta (empresa)</p>
        <input
          aria-label="Nombre de la cuenta"
          placeholder="Nombre de la empresa*"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <input
          aria-label="Sector"
          placeholder="Sector (p. ej. Manufactura)"
          value={form.industry}
          onChange={(e) => setForm({ ...form, industry: e.target.value })}
        />
        <input
          aria-label="Ciudad"
          placeholder="Ciudad"
          value={form.city}
          onChange={(e) => setForm({ ...form, city: e.target.value })}
        />
        <input
          aria-label="País"
          placeholder="País"
          value={form.country}
          onChange={(e) => setForm({ ...form, country: e.target.value })}
        />
        <input
          aria-label="Web"
          placeholder="https://…"
          value={form.website}
          onChange={(e) => setForm({ ...form, website: e.target.value })}
        />
        <input
          aria-label="Teléfono"
          placeholder="Teléfono"
          value={form.phone}
          onChange={(e) => setForm({ ...form, phone: e.target.value })}
        />
        <textarea
          aria-label="Notas"
          placeholder="Notas…"
          value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
        />
        <button type="submit" className="primary-button" disabled={saving}>
          {saving ? "Creando…" : "Crear cuenta"}
        </button>
      </form>
    </section>
  );
}

function AccountRowView({
  account,
  onToggle,
}: {
  account: AccountRow;
  onToggle: () => void;
}) {
  return (
    <tr
      onClick={onToggle}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onToggle();
        }
      }}
      className="account-row"
      role="button"
      tabIndex={0}
      aria-label={`Ver ficha de ${account.name}`}
    >
      <td>
        <strong>{account.name}</strong>
        {!account.is_active && <span className="muted-text"> (inactiva)</span>}
      </td>
      <td>{account.industry ?? "—"}</td>
      <td>{account.city ?? "—"}</td>
      <td>{account.contact_count}</td>
      <td>
        {account.open_count} · {formatValue(account.open_value, "EUR")}
      </td>
      <td>{formatValue(account.won_value, "EUR")}</td>
    </tr>
  );
}
