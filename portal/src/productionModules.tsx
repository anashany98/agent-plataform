import {
  FormEvent,
  ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Activity,
  Bot,
  BookOpen,
  CalendarClock,
  ClipboardList,
  Gauge,
  Globe2,
  ReceiptText,
  ShoppingCart,
} from "lucide-react";
import { apiRequest } from "./api";
import { tryFocusRow } from "./appFormat";
import { CeoChat } from "./ceoChat";

type ModuleProps = {
  token: string;
  refreshRevision: number;
  canWrite: boolean;
};

type ListResponse<T> = { items: T[] };

function request<T>(
  path: string,
  token: string,
  init?: RequestInit,
): Promise<T> {
  return apiRequest<T>(path, { ...init, token });
}

function operationKey(prefix: string): string {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi?.randomUUID === "function") {
    return `portal-${prefix}-${cryptoApi.randomUUID()}`;
  }
  if (typeof cryptoApi?.getRandomValues === "function") {
    const bytes = new Uint32Array(4);
    cryptoApi.getRandomValues(bytes);
    return `portal-${prefix}-${Array.from(bytes, (value) =>
      value.toString(16).padStart(8, "0"),
    ).join("")}`;
  }
  return `portal-${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function versionedKey(prefix: string, id: string, version?: number): string {
  return `portal-${prefix}-${id}${version === undefined ? "" : `-v${version}`}`;
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Fecha no disponible"
    : date.toLocaleString("es-ES", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

function formatMoney(value: string | number, currency: string): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  try {
    return new Intl.NumberFormat("es-ES", {
      style: "currency",
      currency: currency || "EUR",
    }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency || "EUR"}`;
  }
}

function statusPresentation(status: unknown): { tone: string; label: string } {
  const value = typeof status === "string" ? status.trim() : "";
  const normalized = value.toLowerCase();
  const labels: Record<string, string> = {
    active: "Activo",
    approved: "Aprobado",
    cancelled: "Cancelado",
    confirmed: "Confirmado",
    draft: "Borrador",
    expired: "Caducado",
    inactive: "Inactivo",
    paused: "Pausado",
    pending: "Pendiente",
    pending_approval: "Pendiente de aprobación",
    published: "Publicado",
    rejected: "Rechazado",
  };
  if (["active", "approved", "confirmed", "published"].includes(normalized)) {
    return { tone: "ok", label: labels[normalized] ?? value };
  }
  if (["cancelled", "expired", "rejected"].includes(normalized)) {
    return { tone: "error", label: labels[normalized] ?? value };
  }
  if (["draft", "pending", "pending_approval", "paused"].includes(normalized)) {
    return { tone: "warning", label: labels[normalized] ?? value };
  }
  return {
    tone: "muted",
    label: (labels[normalized] ?? value) || "No informado",
  };
}

function StatusBadge({ status }: { status: unknown }) {
  const presentation = statusPresentation(status);
  return (
    <span className={`status ${presentation.tone}`}>{presentation.label}</span>
  );
}

function ModuleHeading({
  eyebrow,
  title,
  count,
  icon,
}: {
  eyebrow: string;
  title: string;
  count?: number;
  icon: ReactNode;
}) {
  return (
    <div className="panel-heading">
      <div>
        <p>{eyebrow}</p>
        <h2>{title}</h2>
      </div>
      <div className="module-heading-meta">
        {icon}
        {typeof count === "number" && (
          <span className="counter" aria-label={`${count} elementos`}>
            {count}
          </span>
        )}
      </div>
    </div>
  );
}

function LoadingOrError({
  loading,
  error,
  empty,
}: {
  loading: boolean;
  error: string;
  empty: boolean;
}) {
  if (error) {
    return (
      <div className="alert error" role="alert">
        {error}
      </div>
    );
  }
  if (loading) {
    return (
      <div className="empty-state compact" role="status">
        Cargando datos reales…
      </div>
    );
  }
  if (empty) {
    return <div className="empty-state compact">No hay registros.</div>;
  }
  return null;
}

function useResourceList<T>(
  path: string,
  token: string,
  refreshRevision: number,
  enabled = true,
) {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState("");
  const requestRevision = useRef(0);

  const reload = useCallback(async () => {
    const revision = ++requestRevision.current;
    if (!enabled) {
      setItems([]);
      setLoading(false);
      setError("");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await request<ListResponse<T>>(path, token);
      if (revision === requestRevision.current) {
        setItems(Array.isArray(data.items) ? data.items : []);
      }
    } catch (err) {
      if (revision === requestRevision.current) {
        setItems([]);
        setError(messageFrom(err, "No se pudieron cargar los datos."));
      }
    } finally {
      if (revision === requestRevision.current) setLoading(false);
    }
  }, [enabled, path, token]);

  useEffect(() => {
    void reload();
    return () => {
      requestRevision.current += 1;
    };
  }, [refreshRevision, reload]);

  return { items, loading, error, reload };
}

function MutationFeedback({
  notice,
  error,
}: {
  notice: string;
  error: string;
}) {
  return (
    <>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="alert info" role="status">
          {notice}
        </div>
      )}
    </>
  );
}

type Customer = {
  id: string;
  name: string;
  email: string;
  phone: string | null;
  company: string | null;
  created_at: string | null;
};

type CommerceItem = {
  product_id?: string;
  sku?: string;
  name?: string;
  qty?: number;
  unit_price?: number;
};

type Quote = {
  id: string;
  customer_id: string;
  items: CommerceItem[];
  grand_total: string;
  currency: string;
  status: string;
  confirmation_expires_at: string | null;
  created_at: string | null;
};

type Order = {
  id: string;
  customer_id: string;
  quote_id: string;
  items: CommerceItem[];
  grand_total: string;
  currency: string;
  status: string;
  created_at: string | null;
};

type Invoice = {
  id: string;
  invoice_number: string | null;
  order_id: string;
  customer_id: string;
  items: CommerceItem[];
  total_amount: string;
  currency: string;
  status: string;
  created_at: string | null;
};

type QuoteCreated = {
  quote_id: string;
  confirmation_token: string;
  grand_total: number;
  currency: string;
};

function ItemDetails({ items }: { items: CommerceItem[] }) {
  const safeItems = Array.isArray(items) ? items : [];
  return (
    <details>
      <summary>{safeItems.length} línea(s)</summary>
      <ul className="detail-list">
        {safeItems.map((item, index) => (
          <li key={`${item.product_id ?? item.sku ?? "item"}-${index}`}>
            <strong>
              {item.name ?? item.sku ?? item.product_id ?? "Producto"}
            </strong>
            <span>
              Cantidad {item.qty ?? "—"}
              {Number.isFinite(Number(item.unit_price))
                ? ` · ${Number(item.unit_price).toFixed(2)} por unidad`
                : ""}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

export function CommerceSection({
  token,
  refreshRevision,
  canWrite,
  active = true,
}: ModuleProps & { active?: boolean }) {
  const customers = useResourceList<Customer>(
    "/customers?limit=100",
    token,
    refreshRevision,
  );
  const quotes = useResourceList<Quote>(
    "/quotes?limit=100",
    token,
    refreshRevision,
  );
  const orders = useResourceList<Order>(
    "/orders?limit=100",
    token,
    refreshRevision,
  );
  const invoices = useResourceList<Invoice>(
    "/invoices?limit=100",
    token,
    refreshRevision,
  );

  // Deep-link desde el digest: enfoca y resalta la factura objetivo. La
  // sección vive en un div oculto y no se desmonta, por eso `active` también
  // reintenta (la clave se pone antes de navegar a #ventas).
  useEffect(() => {
    if (!active) return;
    if (
      tryFocusRow(
        "portal_ventas_focus",
        (id) => `[data-focus-id="${CSS.escape(id)}"]`,
      )
    ) {
      return;
    }
    const timer = window.setTimeout(() => {
      sessionStorage.removeItem("portal_ventas_focus");
    }, 5_000);
    return () => window.clearTimeout(timer);
  }, [active, invoices.items]);

  const [customerForm, setCustomerForm] = useState({
    name: "",
    email: "",
    phone: "",
    company: "",
  });
  const [quoteForm, setQuoteForm] = useState({
    customer_id: "",
    product_id: "",
    qty: "1",
  });
  const [pendingQuote, setPendingQuote] = useState<QuoteCreated | null>(null);
  const [quoteConfirmation, setQuoteConfirmation] = useState("");
  const [mutating, setMutating] = useState("");
  const [notice, setNotice] = useState("");
  const [mutationError, setMutationError] = useState("");
  const customerKey = useRef("");
  const quoteKey = useRef("");

  function updateCustomer(field: keyof typeof customerForm, value: string) {
    customerKey.current = "";
    setCustomerForm((current) => ({ ...current, [field]: value }));
  }

  function updateQuote(field: keyof typeof quoteForm, value: string) {
    quoteKey.current = "";
    setPendingQuote(null);
    setQuoteConfirmation("");
    setQuoteForm((current) => ({ ...current, [field]: value }));
  }

  async function createCustomer(event: FormEvent) {
    event.preventDefault();
    if (!canWrite || mutating) return;
    customerKey.current ||= operationKey("customer-create");
    setMutating("customer");
    setNotice("");
    setMutationError("");
    try {
      const created = await request<Customer>("/customers", token, {
        method: "POST",
        headers: { "Idempotency-Key": customerKey.current },
        body: JSON.stringify({
          name: customerForm.name.trim(),
          email: customerForm.email.trim(),
          phone: customerForm.phone.trim() || null,
          company: customerForm.company.trim() || null,
        }),
      });
      setNotice(`Cliente ${created.name} creado con referencia ${created.id}.`);
      setCustomerForm({ name: "", email: "", phone: "", company: "" });
      customerKey.current = "";
      await customers.reload();
    } catch (err) {
      setMutationError(messageFrom(err, "No se pudo crear el cliente."));
    } finally {
      setMutating("");
    }
  }

  async function createQuote(event: FormEvent) {
    event.preventDefault();
    if (!canWrite || mutating) return;
    const qty = Number(quoteForm.qty);
    if (!Number.isInteger(qty) || qty < 1) {
      setMutationError(
        "La cantidad debe ser un número entero superior a cero.",
      );
      return;
    }
    quoteKey.current ||= operationKey("quote-create");
    setMutating("quote");
    setNotice("");
    setMutationError("");
    try {
      const created = await request<QuoteCreated>("/quotes", token, {
        method: "POST",
        headers: { "Idempotency-Key": quoteKey.current },
        body: JSON.stringify({
          customer_id: quoteForm.customer_id,
          items: [{ product_id: quoteForm.product_id.trim(), qty }],
        }),
      });
      setPendingQuote(created);
      setNotice(
        `Borrador ${created.quote_id} calculado por el servidor: ${formatMoney(
          created.grand_total,
          created.currency,
        )}. Aún no es un pedido.`,
      );
      await quotes.reload();
    } catch (err) {
      setMutationError(messageFrom(err, "No se pudo crear el presupuesto."));
    } finally {
      setMutating("");
    }
  }

  async function confirmQuote() {
    if (
      !pendingQuote ||
      quoteConfirmation.trim() !== pendingQuote.quote_id ||
      mutating
    ) {
      return;
    }
    setMutating("quote-confirm");
    setNotice("");
    setMutationError("");
    try {
      const result = await request<{
        order_id: string;
        invoice_draft_id: string;
        approval_id: string;
      }>(
        `/quotes/${encodeURIComponent(pendingQuote.quote_id)}/confirm`,
        token,
        {
          method: "POST",
          headers: {
            "Idempotency-Key": versionedKey(
              "quote-confirm",
              pendingQuote.quote_id,
            ),
          },
          body: JSON.stringify({
            confirmation_token: pendingQuote.confirmation_token,
          }),
        },
      );
      setNotice(
        `Presupuesto confirmado. Pedido ${result.order_id}; factura ${result.invoice_draft_id} pendiente de aprobación.`,
      );
      setPendingQuote(null);
      setQuoteConfirmation("");
      setQuoteForm({ customer_id: "", product_id: "", qty: "1" });
      quoteKey.current = "";
      await Promise.all([quotes.reload(), orders.reload(), invoices.reload()]);
    } catch (err) {
      setMutationError(
        messageFrom(err, "No se pudo confirmar el presupuesto."),
      );
    } finally {
      setMutating("");
    }
  }

  async function requestInvoiceApproval(invoice: Invoice) {
    if (!canWrite || mutating) return;
    setMutating(`invoice-${invoice.id}`);
    setNotice("");
    setMutationError("");
    try {
      await request(
        `/invoices/${encodeURIComponent(invoice.id)}/request-approval`,
        token,
        {
          method: "POST",
          headers: {
            "Idempotency-Key": versionedKey("invoice-approval", invoice.id),
          },
          body: JSON.stringify({}),
        },
      );
      setNotice(`La factura ${invoice.id} se envió a aprobación humana.`);
      await invoices.reload();
    } catch (err) {
      setMutationError(messageFrom(err, "No se pudo solicitar la aprobación."));
    } finally {
      setMutating("");
    }
  }

  return (
    <section
      id="ventas"
      className="module-stack"
      aria-label="Ventas y facturación"
    >
      <MutationFeedback notice={notice} error={mutationError} />
      <div className="module-grid two-columns">
        <article className="panel">
          <ModuleHeading
            eyebrow="Directorio real"
            title="Clientes"
            count={customers.items.length}
            icon={<ShoppingCart size={20} />}
          />
          <LoadingOrError
            loading={customers.loading}
            error={customers.error}
            empty={customers.items.length === 0}
          />
          {customers.items.length > 0 && (
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Clientes registrados</caption>
                <thead>
                  <tr>
                    <th scope="col">Cliente</th>
                    <th scope="col">Contacto</th>
                    <th scope="col">Alta</th>
                  </tr>
                </thead>
                <tbody>
                  {customers.items.map((customer) => (
                    <tr key={customer.id}>
                      <td>
                        <strong>{customer.name}</strong>
                        <small className="table-subline">{customer.id}</small>
                      </td>
                      <td>
                        {customer.email}
                        <small className="table-subline">
                          {[customer.company, customer.phone]
                            .filter(Boolean)
                            .join(" · ") || "—"}
                        </small>
                      </td>
                      <td>{formatDate(customer.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {canWrite && (
            <form
              className="module-form"
              onSubmit={createCustomer}
              aria-busy={mutating === "customer"}
            >
              <h3>Nuevo cliente</h3>
              <div className="import-grid">
                <label>
                  Nombre
                  <input
                    required
                    minLength={2}
                    maxLength={200}
                    value={customerForm.name}
                    onChange={(event) =>
                      updateCustomer("name", event.target.value)
                    }
                  />
                </label>
                <label>
                  Email
                  <input
                    required
                    type="email"
                    maxLength={320}
                    value={customerForm.email}
                    onChange={(event) =>
                      updateCustomer("email", event.target.value)
                    }
                  />
                </label>
                <label>
                  Empresa
                  <input
                    maxLength={200}
                    value={customerForm.company}
                    onChange={(event) =>
                      updateCustomer("company", event.target.value)
                    }
                  />
                </label>
                <label>
                  Teléfono
                  <input
                    type="tel"
                    maxLength={64}
                    value={customerForm.phone}
                    onChange={(event) =>
                      updateCustomer("phone", event.target.value)
                    }
                  />
                </label>
              </div>
              <button
                className="primary-button"
                type="submit"
                disabled={Boolean(mutating)}
              >
                {mutating === "customer" ? "Creando…" : "Crear cliente"}
              </button>
            </form>
          )}
        </article>

        <article className="panel">
          <ModuleHeading
            eyebrow="Cálculo del servidor"
            title="Presupuestos"
            count={quotes.items.length}
            icon={<ReceiptText size={20} />}
          />
          <LoadingOrError
            loading={quotes.loading}
            error={quotes.error}
            empty={quotes.items.length === 0}
          />
          {quotes.items.length > 0 && (
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Presupuestos registrados</caption>
                <thead>
                  <tr>
                    <th scope="col">Referencia</th>
                    <th scope="col">Cliente</th>
                    <th scope="col">Total</th>
                    <th scope="col">Estado</th>
                    <th scope="col">Detalle</th>
                  </tr>
                </thead>
                <tbody>
                  {quotes.items.map((quote) => (
                    <tr key={quote.id}>
                      <td>{quote.id}</td>
                      <td>{quote.customer_id}</td>
                      <td>{formatMoney(quote.grand_total, quote.currency)}</td>
                      <td>
                        <StatusBadge status={quote.status} />
                      </td>
                      <td>
                        <ItemDetails items={quote.items} />
                        <small className="table-subline">
                          Caduca: {formatDate(quote.confirmation_expires_at)}
                        </small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {canWrite && (
            <form
              className="module-form"
              onSubmit={createQuote}
              aria-busy={mutating === "quote"}
            >
              <h3>Crear borrador de presupuesto</h3>
              <p className="form-help">
                Precio, impuestos, envío y disponibilidad los determina el
                servidor; el portal no acepta totales manuales.
              </p>
              <div className="import-grid">
                <label>
                  Cliente
                  <select
                    required
                    value={quoteForm.customer_id}
                    onChange={(event) =>
                      updateQuote("customer_id", event.target.value)
                    }
                  >
                    <option value="">Selecciona un cliente</option>
                    {customers.items.map((customer) => (
                      <option value={customer.id} key={customer.id}>
                        {customer.name} · {customer.id}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  ID de producto
                  <input
                    required
                    maxLength={150}
                    value={quoteForm.product_id}
                    onChange={(event) =>
                      updateQuote("product_id", event.target.value)
                    }
                  />
                </label>
                <label>
                  Cantidad
                  <input
                    required
                    type="number"
                    min={1}
                    max={100000}
                    step={1}
                    value={quoteForm.qty}
                    onChange={(event) => updateQuote("qty", event.target.value)}
                  />
                </label>
              </div>
              <button
                className="primary-button"
                type="submit"
                disabled={Boolean(mutating) || customers.items.length === 0}
              >
                {mutating === "quote" ? "Calculando…" : "Crear borrador"}
              </button>
            </form>
          )}
          {pendingQuote && (
            <div
              className="confirmation-card"
              aria-label="Confirmar presupuesto"
            >
              <strong>Confirmación de pedido</strong>
              <span>
                {pendingQuote.quote_id} ·{" "}
                {formatMoney(pendingQuote.grand_total, pendingQuote.currency)}.
                Confirmar reservará stock y generará pedido y factura borrador.
              </span>
              <label>
                Escribe la referencia exacta
                <input
                  value={quoteConfirmation}
                  onChange={(event) => setQuoteConfirmation(event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <button
                type="button"
                className="success-button"
                disabled={
                  Boolean(mutating) ||
                  quoteConfirmation.trim() !== pendingQuote.quote_id
                }
                onClick={() => void confirmQuote()}
              >
                {mutating === "quote-confirm"
                  ? "Confirmando…"
                  : "Confirmar y crear pedido"}
              </button>
            </div>
          )}
        </article>
      </div>

      <div className="module-grid two-columns">
        <article className="panel">
          <ModuleHeading
            eyebrow="Venta confirmada"
            title="Pedidos"
            count={orders.items.length}
            icon={<ShoppingCart size={20} />}
          />
          <LoadingOrError
            loading={orders.loading}
            error={orders.error}
            empty={orders.items.length === 0}
          />
          {orders.items.length > 0 && (
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Pedidos registrados</caption>
                <thead>
                  <tr>
                    <th scope="col">Pedido</th>
                    <th scope="col">Presupuesto</th>
                    <th scope="col">Total</th>
                    <th scope="col">Estado</th>
                    <th scope="col">Detalle</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.items.map((order) => (
                    <tr key={order.id}>
                      <td>
                        {order.id}
                        <small className="table-subline">
                          {formatDate(order.created_at)}
                        </small>
                      </td>
                      <td>{order.quote_id}</td>
                      <td>{formatMoney(order.grand_total, order.currency)}</td>
                      <td>
                        <StatusBadge status={order.status} />
                      </td>
                      <td>
                        <ItemDetails items={order.items} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
        <article className="panel">
          <ModuleHeading
            eyebrow="Emisión controlada"
            title="Facturas"
            count={invoices.items.length}
            icon={<ReceiptText size={20} />}
          />
          <LoadingOrError
            loading={invoices.loading}
            error={invoices.error}
            empty={invoices.items.length === 0}
          />
          {invoices.items.length > 0 && (
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Facturas registradas</caption>
                <thead>
                  <tr>
                    <th scope="col">Factura</th>
                    <th scope="col">Pedido</th>
                    <th scope="col">Total</th>
                    <th scope="col">Estado</th>
                    <th scope="col">Acción</th>
                  </tr>
                </thead>
                <tbody>
                  {invoices.items.map((invoice) => (
                    <tr key={invoice.id} data-focus-id={invoice.id}>
                      <td>
                        {invoice.invoice_number || invoice.id}
                        <small className="table-subline">{invoice.id}</small>
                      </td>
                      <td>{invoice.order_id}</td>
                      <td>
                        {formatMoney(invoice.total_amount, invoice.currency)}
                      </td>
                      <td>
                        <StatusBadge status={invoice.status} />
                      </td>
                      <td>
                        {canWrite && invoice.status === "draft" ? (
                          <button
                            type="button"
                            className="secondary-button"
                            disabled={Boolean(mutating)}
                            onClick={() => void requestInvoiceApproval(invoice)}
                          >
                            {mutating === `invoice-${invoice.id}`
                              ? "Enviando…"
                              : "Solicitar aprobación"}
                          </button>
                        ) : (
                          <span className="muted-text">
                            Sin acciones disponibles
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </div>
    </section>
  );
}

type WikiPage = {
  id: string;
  slug: string;
  title: string;
  content: string;
  status: string;
  version: number;
  updated_at: string | null;
  published_at: string | null;
};

type SeoProject = {
  id: string;
  name: string;
  domain: string;
  configuration: Record<string, unknown>;
  status: string;
  version: number;
  updated_at: string | null;
  analysis_engine?: string;
  engine?: string;
  external_crawler?: string;
};

type LandingPage = {
  id: string;
  slug: string;
  title: string;
  content: Record<string, string>;
  status: string;
  version: number;
  updated_at: string | null;
  approved_at: string | null;
  render_engine?: string;
  external_publication?: string;
};

type SeoAnalysis = {
  analysis_id: string;
  result: {
    method: string;
    external_fetch_performed: boolean;
    measured: {
      title?: string;
      h1_count?: number;
      images_total?: number;
      images_missing_alt?: number;
      links_total?: number;
    };
    recommendations: Array<{
      code: string;
      priority: string;
      action: string;
    }>;
  };
};

export function ContentGrowthSection({
  token,
  refreshRevision,
  canWrite,
}: ModuleProps) {
  const wiki = useResourceList<WikiPage>("/wiki/pages", token, refreshRevision);
  const seo = useResourceList<SeoProject>(
    "/seo/projects",
    token,
    refreshRevision,
  );
  const landings = useResourceList<LandingPage>(
    "/landing-pages",
    token,
    refreshRevision,
  );
  const [wikiForm, setWikiForm] = useState({
    slug: "",
    title: "",
    content: "",
  });
  const [seoForm, setSeoForm] = useState({ name: "", domain: "" });
  const [landingForm, setLandingForm] = useState({
    slug: "",
    title: "",
    headline: "",
    body: "",
    cta: "Contactar",
  });
  const [analysisForm, setAnalysisForm] = useState({
    project_id: "",
    page_url: "",
    html: "",
  });
  const [analysis, setAnalysis] = useState<SeoAnalysis | null>(null);
  const [mutating, setMutating] = useState("");
  const [notice, setNotice] = useState("");
  const [mutationError, setMutationError] = useState("");
  const wikiKey = useRef("");
  const seoKey = useRef("");
  const landingKey = useRef("");
  const analysisKey = useRef("");

  function beginMutation(name: string) {
    setMutating(name);
    setNotice("");
    setMutationError("");
  }

  function finishMutation() {
    setMutating("");
  }

  async function createWiki(event: FormEvent) {
    event.preventDefault();
    if (!canWrite || mutating) return;
    wikiKey.current ||= operationKey("wiki-create");
    beginMutation("wiki-create");
    try {
      const created = await request<WikiPage>("/wiki/pages", token, {
        method: "POST",
        headers: { "Idempotency-Key": wikiKey.current },
        body: JSON.stringify({
          slug: wikiForm.slug.trim(),
          title: wikiForm.title.trim(),
          content: wikiForm.content,
        }),
      });
      setNotice(
        `Página wiki ${created.id} guardada como borrador v${created.version}.`,
      );
      setWikiForm({ slug: "", title: "", content: "" });
      wikiKey.current = "";
      await wiki.reload();
    } catch (err) {
      setMutationError(messageFrom(err, "No se pudo crear la página wiki."));
    } finally {
      finishMutation();
    }
  }

  async function createSeo(event: FormEvent) {
    event.preventDefault();
    if (!canWrite || mutating) return;
    seoKey.current ||= operationKey("seo-create");
    beginMutation("seo-create");
    try {
      const created = await request<SeoProject>("/seo/projects", token, {
        method: "POST",
        headers: { "Idempotency-Key": seoKey.current },
        body: JSON.stringify({
          name: seoForm.name.trim(),
          domain: seoForm.domain.trim().toLowerCase(),
          configuration: {},
        }),
      });
      setNotice(
        `Proyecto SEO ${created.id} creado como borrador. No se ha ejecutado rastreo externo.`,
      );
      setSeoForm({ name: "", domain: "" });
      seoKey.current = "";
      await seo.reload();
    } catch (err) {
      setMutationError(messageFrom(err, "No se pudo crear el proyecto SEO."));
    } finally {
      finishMutation();
    }
  }

  async function createLanding(event: FormEvent) {
    event.preventDefault();
    if (!canWrite || mutating) return;
    landingKey.current ||= operationKey("landing-create");
    beginMutation("landing-create");
    try {
      const created = await request<LandingPage>("/landing-pages", token, {
        method: "POST",
        headers: { "Idempotency-Key": landingKey.current },
        body: JSON.stringify({
          slug: landingForm.slug.trim(),
          title: landingForm.title.trim(),
          content: {
            headline: landingForm.headline.trim(),
            body: landingForm.body.trim(),
            cta: landingForm.cta.trim(),
          },
        }),
      });
      setNotice(
        `Landing ${created.id} guardada como borrador. No está publicada externamente.`,
      );
      setLandingForm({
        slug: "",
        title: "",
        headline: "",
        body: "",
        cta: "Contactar",
      });
      landingKey.current = "";
      await landings.reload();
    } catch (err) {
      setMutationError(messageFrom(err, "No se pudo crear la landing."));
    } finally {
      finishMutation();
    }
  }

  async function requestVersionedApproval(
    kind: "wiki" | "landing",
    resource: WikiPage | LandingPage,
  ) {
    if (!canWrite || mutating) return;
    const path =
      kind === "wiki"
        ? `/wiki/pages/${encodeURIComponent(resource.id)}/request-publication`
        : `/landing-pages/${encodeURIComponent(resource.id)}/request-approval`;
    beginMutation(`${kind}-${resource.id}`);
    try {
      await request(path, token, {
        method: "POST",
        headers: {
          "If-Match": String(resource.version),
          "Idempotency-Key": versionedKey(
            `${kind}-approval`,
            resource.id,
            resource.version,
          ),
        },
        body: JSON.stringify({}),
      });
      setNotice(
        kind === "wiki"
          ? `La publicación interna de ${resource.id} queda pendiente de aprobación humana.`
          : `La landing ${resource.id} queda pendiente de aprobación; la publicación externa sigue sin ejecutarse.`,
      );
      await (kind === "wiki" ? wiki.reload() : landings.reload());
    } catch (err) {
      setMutationError(messageFrom(err, "No se pudo solicitar la aprobación."));
    } finally {
      finishMutation();
    }
  }

  async function analyzeHtml(event: FormEvent) {
    event.preventDefault();
    if (mutating) return;
    analysisKey.current ||= operationKey("seo-html-analysis");
    beginMutation("seo-analysis");
    setAnalysis(null);
    try {
      const result = await request<SeoAnalysis>(
        `/seo/projects/${encodeURIComponent(analysisForm.project_id)}/analyze-html`,
        token,
        {
          method: "POST",
          headers: { "Idempotency-Key": analysisKey.current },
          body: JSON.stringify({
            html: analysisForm.html,
            page_url: analysisForm.page_url.trim() || null,
          }),
        },
      );
      setAnalysis(result);
      setNotice(
        `Análisis estático ${result.analysis_id} completado sobre el HTML aportado; no se realizó ninguna descarga externa.`,
      );
    } catch (err) {
      setMutationError(messageFrom(err, "No se pudo analizar el HTML."));
    } finally {
      finishMutation();
    }
  }

  return (
    <section
      id="contenido"
      className="module-stack"
      aria-label="Contenido, SEO y landings"
    >
      <div className="alert warning" role="status">
        Estados honestos: la wiki se publica solo dentro de la plataforma, SEO
        analiza únicamente HTML pegado y las landings no tienen publicación
        externa implementada.
      </div>
      {!canWrite && (
        <div className="alert info">
          Tu rol permite consultar y ejecutar análisis estático SEO, pero no
          crear ni enviar contenido a aprobación.
        </div>
      )}
      <MutationFeedback notice={notice} error={mutationError} />
      <div className="module-grid three-columns">
        <article className="panel">
          <ModuleHeading
            eyebrow="Conocimiento interno"
            title="Wiki"
            count={wiki.items.length}
            icon={<BookOpen size={20} />}
          />
          <LoadingOrError
            loading={wiki.loading}
            error={wiki.error}
            empty={wiki.items.length === 0}
          />
          {wiki.items.length > 0 && (
            <div className="resource-list">
              {wiki.items.map((page) => (
                <article className="resource-card" key={page.id}>
                  <div>
                    <strong>{page.title}</strong>
                    <StatusBadge status={page.status} />
                  </div>
                  <span>
                    /{page.slug} · v{page.version} ·{" "}
                    {formatDate(page.updated_at)}
                  </span>
                  <details>
                    <summary>Ver contenido</summary>
                    <pre>{page.content}</pre>
                  </details>
                  {canWrite && ["draft", "rejected"].includes(page.status) && (
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={Boolean(mutating)}
                      onClick={() =>
                        void requestVersionedApproval("wiki", page)
                      }
                    >
                      {mutating === `wiki-${page.id}`
                        ? "Enviando…"
                        : "Solicitar publicación interna"}
                    </button>
                  )}
                </article>
              ))}
            </div>
          )}
          {canWrite && (
            <form
              className="module-form"
              onSubmit={createWiki}
              aria-busy={mutating === "wiki-create"}
            >
              <h3>Nueva página borrador</h3>
              <label>
                Slug
                <input
                  required
                  pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                  maxLength={160}
                  value={wikiForm.slug}
                  onChange={(event) => {
                    wikiKey.current = "";
                    setWikiForm((current) => ({
                      ...current,
                      slug: event.target.value,
                    }));
                  }}
                />
              </label>
              <label>
                Título
                <input
                  required
                  minLength={3}
                  maxLength={240}
                  value={wikiForm.title}
                  onChange={(event) => {
                    wikiKey.current = "";
                    setWikiForm((current) => ({
                      ...current,
                      title: event.target.value,
                    }));
                  }}
                />
              </label>
              <label>
                Contenido
                <textarea
                  required
                  rows={6}
                  maxLength={200000}
                  value={wikiForm.content}
                  onChange={(event) => {
                    wikiKey.current = "";
                    setWikiForm((current) => ({
                      ...current,
                      content: event.target.value,
                    }));
                  }}
                />
              </label>
              <button
                className="primary-button"
                type="submit"
                disabled={Boolean(mutating)}
              >
                {mutating === "wiki-create" ? "Guardando…" : "Guardar borrador"}
              </button>
            </form>
          )}
        </article>

        <article className="panel">
          <ModuleHeading
            eyebrow="Medición determinista"
            title="SEO técnico"
            count={seo.items.length}
            icon={<Globe2 size={20} />}
          />
          <LoadingOrError
            loading={seo.loading}
            error={seo.error}
            empty={seo.items.length === 0}
          />
          {seo.items.length > 0 && (
            <div className="resource-list">
              {seo.items.map((project) => (
                <article className="resource-card" key={project.id}>
                  <div>
                    <strong>{project.name}</strong>
                    <StatusBadge status={project.status} />
                  </div>
                  <span>
                    {project.domain} · v{project.version}
                  </span>
                  <small>
                    Motor:{" "}
                    {project.analysis_engine ??
                      project.engine ??
                      "deterministic_html_static_v1"}
                  </small>
                  <small>Rastreador externo: no implementado</small>
                </article>
              ))}
            </div>
          )}
          {canWrite && (
            <form
              className="module-form"
              onSubmit={createSeo}
              aria-busy={mutating === "seo-create"}
            >
              <h3>Nuevo proyecto borrador</h3>
              <label>
                Nombre
                <input
                  required
                  minLength={3}
                  maxLength={240}
                  value={seoForm.name}
                  onChange={(event) => {
                    seoKey.current = "";
                    setSeoForm((current) => ({
                      ...current,
                      name: event.target.value,
                    }));
                  }}
                />
              </label>
              <label>
                Dominio
                <input
                  required
                  placeholder="ejemplo.com"
                  maxLength={253}
                  value={seoForm.domain}
                  onChange={(event) => {
                    seoKey.current = "";
                    setSeoForm((current) => ({
                      ...current,
                      domain: event.target.value,
                    }));
                  }}
                />
              </label>
              <button
                className="primary-button"
                type="submit"
                disabled={Boolean(mutating)}
              >
                {mutating === "seo-create" ? "Guardando…" : "Crear proyecto"}
              </button>
            </form>
          )}
          <form
            className="module-form"
            onSubmit={analyzeHtml}
            aria-busy={mutating === "seo-analysis"}
          >
            <h3>Analizar HTML aportado</h3>
            <p className="form-help">
              No descarga la URL ni ejecuta JavaScript; mide solo el HTML que
              pegues.
            </p>
            <label>
              Proyecto
              <select
                required
                value={analysisForm.project_id}
                onChange={(event) => {
                  analysisKey.current = "";
                  setAnalysis(null);
                  setAnalysisForm((current) => ({
                    ...current,
                    project_id: event.target.value,
                  }));
                }}
              >
                <option value="">Selecciona un proyecto</option>
                {seo.items.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.domain}
                  </option>
                ))}
              </select>
            </label>
            <label>
              URL de referencia (opcional)
              <input
                type="url"
                maxLength={2048}
                value={analysisForm.page_url}
                onChange={(event) => {
                  analysisKey.current = "";
                  setAnalysisForm((current) => ({
                    ...current,
                    page_url: event.target.value,
                  }));
                }}
              />
            </label>
            <label>
              HTML
              <textarea
                required
                rows={6}
                maxLength={1000000}
                value={analysisForm.html}
                onChange={(event) => {
                  analysisKey.current = "";
                  setAnalysis(null);
                  setAnalysisForm((current) => ({
                    ...current,
                    html: event.target.value,
                  }));
                }}
              />
            </label>
            <button
              className="primary-button"
              type="submit"
              disabled={Boolean(mutating) || seo.items.length === 0}
            >
              {mutating === "seo-analysis"
                ? "Analizando…"
                : "Ejecutar análisis estático"}
            </button>
          </form>
          {analysis && (
            <div className="analysis-result" role="status">
              <strong>Resultado medido</strong>
              <dl>
                <div>
                  <dt>Título</dt>
                  <dd>{analysis.result.measured.title || "No detectado"}</dd>
                </div>
                <div>
                  <dt>H1</dt>
                  <dd>{analysis.result.measured.h1_count ?? 0}</dd>
                </div>
                <div>
                  <dt>Imágenes sin alt</dt>
                  <dd>
                    {analysis.result.measured.images_missing_alt ?? 0} /{" "}
                    {analysis.result.measured.images_total ?? 0}
                  </dd>
                </div>
                <div>
                  <dt>Enlaces</dt>
                  <dd>{analysis.result.measured.links_total ?? 0}</dd>
                </div>
              </dl>
              <span>
                Descarga externa:{" "}
                {analysis.result.external_fetch_performed ? "sí" : "no"}
              </span>
              {analysis.result.recommendations.length > 0 && (
                <ul>
                  {analysis.result.recommendations.slice(0, 5).map((item) => (
                    <li key={item.code}>
                      <strong>{item.priority}</strong>: {item.action}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </article>

        <article className="panel">
          <ModuleHeading
            eyebrow="Borradores aprobables"
            title="Landing pages"
            count={landings.items.length}
            icon={<Globe2 size={20} />}
          />
          <LoadingOrError
            loading={landings.loading}
            error={landings.error}
            empty={landings.items.length === 0}
          />
          {landings.items.length > 0 && (
            <div className="resource-list">
              {landings.items.map((page) => (
                <article className="resource-card" key={page.id}>
                  <div>
                    <strong>{page.title}</strong>
                    <StatusBadge status={page.status} />
                  </div>
                  <span>
                    /{page.slug} · v{page.version}
                  </span>
                  <details>
                    <summary>Ver contenido estructurado</summary>
                    <dl>
                      {Object.entries(page.content ?? {}).map(
                        ([field, value]) => (
                          <div key={field}>
                            <dt>{field}</dt>
                            <dd>{value}</dd>
                          </div>
                        ),
                      )}
                    </dl>
                  </details>
                  <small>
                    Render local: {page.render_engine ?? "determinista"}
                  </small>
                  <small>Publicación externa: no implementada</small>
                  {canWrite && ["draft", "rejected"].includes(page.status) && (
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={Boolean(mutating)}
                      onClick={() =>
                        void requestVersionedApproval("landing", page)
                      }
                    >
                      {mutating === `landing-${page.id}`
                        ? "Enviando…"
                        : "Solicitar aprobación"}
                    </button>
                  )}
                </article>
              ))}
            </div>
          )}
          {canWrite && (
            <form
              className="module-form"
              onSubmit={createLanding}
              aria-busy={mutating === "landing-create"}
            >
              <h3>Nueva landing borrador</h3>
              <label>
                Slug
                <input
                  required
                  pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                  maxLength={160}
                  value={landingForm.slug}
                  onChange={(event) => {
                    landingKey.current = "";
                    setLandingForm((current) => ({
                      ...current,
                      slug: event.target.value,
                    }));
                  }}
                />
              </label>
              <label>
                Título
                <input
                  required
                  minLength={3}
                  maxLength={240}
                  value={landingForm.title}
                  onChange={(event) => {
                    landingKey.current = "";
                    setLandingForm((current) => ({
                      ...current,
                      title: event.target.value,
                    }));
                  }}
                />
              </label>
              <label>
                Titular
                <input
                  required
                  maxLength={500}
                  value={landingForm.headline}
                  onChange={(event) => {
                    landingKey.current = "";
                    setLandingForm((current) => ({
                      ...current,
                      headline: event.target.value,
                    }));
                  }}
                />
              </label>
              <label>
                Cuerpo
                <textarea
                  rows={4}
                  maxLength={5000}
                  value={landingForm.body}
                  onChange={(event) => {
                    landingKey.current = "";
                    setLandingForm((current) => ({
                      ...current,
                      body: event.target.value,
                    }));
                  }}
                />
              </label>
              <label>
                CTA
                <input
                  required
                  maxLength={200}
                  value={landingForm.cta}
                  onChange={(event) => {
                    landingKey.current = "";
                    setLandingForm((current) => ({
                      ...current,
                      cta: event.target.value,
                    }));
                  }}
                />
              </label>
              <button
                className="primary-button"
                type="submit"
                disabled={Boolean(mutating)}
              >
                {mutating === "landing-create"
                  ? "Guardando…"
                  : "Guardar borrador"}
              </button>
            </form>
          )}
        </article>
      </div>
    </section>
  );
}

type ScheduledTask = {
  id: string;
  name: string;
  task_type: string;
  payload: Record<string, unknown>;
  interval_seconds: number;
  status: string;
  version: number;
  next_run_at: string | null;
  last_run_at: string | null;
};

export function SchedulerSection({
  token,
  refreshRevision,
  canWrite,
}: ModuleProps) {
  const tasks = useResourceList<ScheduledTask>(
    "/scheduled-tasks",
    token,
    refreshRevision,
    canWrite,
  );
  const [form, setForm] = useState({ name: "", interval_seconds: "3600" });
  const [mutating, setMutating] = useState("");
  const [notice, setNotice] = useState("");
  const [mutationError, setMutationError] = useState("");
  const createKey = useRef("");

  function updateForm(field: keyof typeof form, value: string) {
    createKey.current = "";
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function createTask(event: FormEvent) {
    event.preventDefault();
    if (!canWrite || mutating) return;
    const interval = Number(form.interval_seconds);
    if (!Number.isInteger(interval) || interval < 60 || interval > 2_592_000) {
      setMutationError(
        "El intervalo debe estar entre 60 y 2.592.000 segundos.",
      );
      return;
    }
    createKey.current ||= operationKey("scheduled-task-create");
    setMutating("create");
    setNotice("");
    setMutationError("");
    try {
      const created = await request<ScheduledTask>("/scheduled-tasks", token, {
        method: "POST",
        headers: { "Idempotency-Key": createKey.current },
        body: JSON.stringify({
          name: form.name.trim(),
          task_type: "automation_sweep",
          payload: {},
          interval_seconds: interval,
        }),
      });
      setNotice(
        `Tarea ${created.id} guardada como borrador. No se ejecutará hasta su aprobación y activación.`,
      );
      setForm({ name: "", interval_seconds: "3600" });
      createKey.current = "";
      await tasks.reload();
    } catch (err) {
      setMutationError(messageFrom(err, "No se pudo crear la tarea."));
    } finally {
      setMutating("");
    }
  }

  async function requestActivation(task: ScheduledTask) {
    if (!canWrite || mutating) return;
    setMutating(task.id);
    setNotice("");
    setMutationError("");
    try {
      await request(
        `/scheduled-tasks/${encodeURIComponent(task.id)}/request-activation`,
        token,
        {
          method: "POST",
          headers: {
            "If-Match": String(task.version),
            "Idempotency-Key": versionedKey(
              "scheduled-task-activation",
              task.id,
              task.version,
            ),
          },
          body: JSON.stringify({}),
        },
      );
      setNotice(
        `La activación de ${task.id} está pendiente de aprobación humana; aún no se ejecuta.`,
      );
      await tasks.reload();
    } catch (err) {
      setMutationError(messageFrom(err, "No se pudo solicitar la activación."));
    } finally {
      setMutating("");
    }
  }

  return (
    <section
      id="tareas"
      className="module-stack"
      aria-label="Tareas programadas"
    >
      <div className="alert warning" role="status">
        Crear una tarea solo genera un borrador. La ejecución automática exige
        aprobación humana y estado activo.
      </div>
      <MutationFeedback notice={notice} error={mutationError} />
      <article className="panel">
        <ModuleHeading
          eyebrow="Planificador persistido"
          title="Tareas programadas"
          count={tasks.items.length}
          icon={<CalendarClock size={20} />}
        />
        <LoadingOrError
          loading={tasks.loading}
          error={tasks.error}
          empty={tasks.items.length === 0}
        />
        {tasks.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <caption className="sr-only">
                Tareas programadas registradas
              </caption>
              <thead>
                <tr>
                  <th scope="col">Tarea</th>
                  <th scope="col">Intervalo</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Ejecuciones</th>
                  <th scope="col">Acción</th>
                </tr>
              </thead>
              <tbody>
                {tasks.items.map((task) => (
                  <tr key={task.id}>
                    <td>
                      <strong>{task.name}</strong>
                      <small className="table-subline">
                        {task.id} · {task.task_type} · v{task.version}
                      </small>
                    </td>
                    <td>{task.interval_seconds.toLocaleString("es-ES")} s</td>
                    <td>
                      <StatusBadge status={task.status} />
                    </td>
                    <td>
                      Próxima: {formatDate(task.next_run_at)}
                      <small className="table-subline">
                        Última: {formatDate(task.last_run_at)}
                      </small>
                    </td>
                    <td>
                      {["draft", "paused", "rejected"].includes(task.status) ? (
                        <button
                          type="button"
                          className="secondary-button"
                          disabled={Boolean(mutating)}
                          onClick={() => void requestActivation(task)}
                        >
                          {mutating === task.id
                            ? "Enviando…"
                            : "Solicitar activación"}
                        </button>
                      ) : (
                        <span className="muted-text">
                          Sin acciones disponibles
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <form
          className="module-form"
          onSubmit={createTask}
          aria-busy={mutating === "create"}
        >
          <h3>Nueva tarea borrador</h3>
          <p className="form-help">
            El único tipo habilitado es el barrido de automatizaciones. La
            ejecución manual de tareas vencidas no se expone en el portal.
          </p>
          <div className="import-grid">
            <label>
              Nombre
              <input
                required
                minLength={3}
                maxLength={200}
                value={form.name}
                onChange={(event) => updateForm("name", event.target.value)}
              />
            </label>
            <label>
              Intervalo (segundos)
              <input
                required
                type="number"
                min={60}
                max={2592000}
                step={1}
                value={form.interval_seconds}
                onChange={(event) =>
                  updateForm("interval_seconds", event.target.value)
                }
              />
            </label>
            <label>
              Tipo
              <input value="automation_sweep" readOnly aria-readonly="true" />
            </label>
          </div>
          <button
            className="primary-button"
            type="submit"
            disabled={Boolean(mutating)}
          >
            {mutating === "create" ? "Guardando…" : "Guardar borrador"}
          </button>
        </form>
      </article>
    </section>
  );
}

type AgentDefinition = {
  agent_id: string;
  name: string;
  purpose: string;
  prompt?: string;
  autonomy_level?: string;
  allowed_tools?: string[];
  primary_model?: string;
  fallback_model?: string;
  monthly_budget_usd?: number | string;
  status: string;
  version?: number;
  persisted?: boolean;
  module?: string;
  module_label?: string;
  scope?: string;
};

type SupervisionTool = {
  name: string;
  kind: string;
  declared: boolean;
  authorized: boolean;
  calls: number;
  success: number;
  denied: number;
  errors: number;
  last_status: string | null;
  last_at: string | null;
};

type SupervisionAction = {
  timestamp: string;
  tool: string;
  status: string;
  detail: string | null;
};

type AgentSupervision = {
  agent_id: string;
  name: string;
  module?: string;
  module_label?: string;
  scope?: string;
  autonomy_level?: string;
  status: string;
  persisted?: boolean;
  allowed_tools: string[];
  authorized_tools: string[];
  tools: SupervisionTool[];
  summary: {
    calls: number;
    success: number;
    denied: number;
    errors: number;
    last_activity_at: string | null;
  };
  recent_actions: SupervisionAction[];
};

function formatActivityAt(value: string | null): string {
  if (!value) return "sin actividad";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("es-ES", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// El objetivo humanizado del digest enlaza a la ficha del registro en su
// módulo: guarda el id a enfocar en sessionStorage y navega al hash. Los
// módulos destino consumen la clave y resaltan la fila (scroll + flash).
const TARGET_MODULE_LINKS: Record<
  string,
  { hash: string; focusKey?: string; label: string }
> = {
  lead: {
    hash: "clientes",
    focusKey: "portal_clientes_focus",
    label: "Abrir el lead en Clientes",
  },
  opportunity: {
    hash: "clientes",
    focusKey: "portal_clientes_focus",
    label: "Abrir la oportunidad en Clientes",
  },
  contact: {
    hash: "clientes",
    focusKey: "portal_clientes_focus",
    label: "Abrir el contacto en Clientes",
  },
  social_message: {
    hash: "clientes",
    label: "Abrir en Clientes (escucha social)",
  },
  task: {
    hash: "clientes",
    focusKey: "portal_clientes_focus",
    label: "Abrir la tarea en Clientes",
  },
  campaign: { hash: "clientes", label: "Abrir la campaña en Clientes" },
  invoice: {
    hash: "ventas",
    focusKey: "portal_ventas_focus",
    label: "Abrir la factura en Ventas",
  },
  product: {
    hash: "catalogo",
    focusKey: "portal_catalogo_focus",
    label: "Abrir el producto en Catálogo",
  },
  automation: { hash: "automatizaciones", label: "Abrir en Automatizaciones" },
};

function openTarget(
  kind: string | undefined,
  focusId: string | null | undefined,
) {
  const link = TARGET_MODULE_LINKS[kind ?? ""];
  if (!link) return;
  if (link.focusKey && focusId) {
    sessionStorage.setItem(link.focusKey, focusId);
  }
  window.location.hash = link.hash;
}

export function AgentRegistrySection({
  token,
  refreshRevision,
  canWrite,
}: ModuleProps) {
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [supervision, setSupervision] = useState<AgentSupervision[]>([]);
  const [supervisionLoading, setSupervisionLoading] = useState(true);
  const [supervisionError, setSupervisionError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [mutating, setMutating] = useState("");
  const [notice, setNotice] = useState("");
  const [mutationError, setMutationError] = useState("");
  const [form, setForm] = useState({
    agent_id: "",
    name: "",
    purpose: "",
    prompt: "",
    allowed_tools: "search_products",
    monthly_budget_usd: "20.00",
  });
  const createKey = useRef("");
  const requestRevision = useRef(0);

  // Autonomía por excepción (T-068): umbrales por agente + digest de
  // decisiones auto-ejecutadas con revert.
  interface AutonomyAgent {
    agent_id: string;
    name: string;
    module_label?: string;
    autonomy_level?: string;
    mode: "manual" | "autonomous";
    max_value_threshold: number;
    allow_follow_ups: boolean;
    allow_spam_dismissals: boolean;
    notify_on_deviation_only: boolean;
    allowed_actions: string[];
    max_actions_per_day: number;
  }
  interface DigestDecision {
    id: string;
    agent_id: string;
    agent_label?: string;
    action_type: string;
    action_label?: string;
    target_key: string;
    target_kind?: string;
    target_focus_id?: string | null;
    target_label?: string;
    executed_at: string;
    deviation: boolean;
    deviation_reason?: string | null;
    reverted: boolean;
    reverted_by?: string | null;
    reverted_at?: string | null;
  }
  interface AgentDigest {
    window_days: number;
    total_decisions: number;
    by_agent: Array<{
      agent_id: string;
      agent_label?: string;
      total: number;
      deviations: number;
      reverted: number;
      deviations_only: boolean;
    }>;
    pending_human_approvals: number;
    decisions: DigestDecision[];
  }
  const [autonomy, setAutonomy] = useState<AutonomyAgent[]>([]);
  const [autonomyLoading, setAutonomyLoading] = useState(true);
  const [autonomyError, setAutonomyError] = useState("");
  const [safeActions, setSafeActions] = useState<Record<string, string>>({});
  const [digest, setDigest] = useState<AgentDigest | null>(null);
  const [digestError, setDigestError] = useState("");
  const [autonomyDraft, setAutonomyDraft] = useState<
    Record<string, AutonomyAgent>
  >({});
  const [autonomyNotice, setAutonomyNotice] = useState("");
  const [reverting, setReverting] = useState("");

  const FOLLOW_UP_ACTION_KEYS = [
    "agent_proposal:create_follow_up",
    "agent_proposal:ceo_follow_up",
  ];
  const DISMISS_ACTION_KEY = "agent_proposal:dismiss_message";

  const saveAutonomy = useCallback(
    async (agentId: string) => {
      const draft = autonomyDraft[agentId];
      if (!draft) return;
      setAutonomyNotice("");
      try {
        const allowed = draft.allowed_actions ?? [];
        await request(`/agents/autonomy/${agentId}`, token, {
          method: "PUT",
          body: JSON.stringify({
            mode: draft.mode,
            max_value_threshold: draft.max_value_threshold,
            allow_follow_ups: allowed.some((action) =>
              FOLLOW_UP_ACTION_KEYS.includes(action),
            ),
            allow_spam_dismissals: allowed.includes(DISMISS_ACTION_KEY),
            notify_on_deviation_only: draft.notify_on_deviation_only,
            allowed_actions: allowed,
            max_actions_per_day: draft.max_actions_per_day,
          }),
        });
        setAutonomy((current) =>
          current.map((agent) => (agent.agent_id === agentId ? draft : agent)),
        );
        setAutonomyNotice(
          `Autonomía de «${draft.name}» actualizada (${draft.mode}).`,
        );
      } catch (err) {
        setAutonomyError(
          messageFrom(err, "No se pudo guardar la autonomía del agente."),
        );
      }
    },
    [autonomyDraft, token],
  );

  const revertDecision = useCallback(
    async (decision: DigestDecision) => {
      setReverting(decision.id);
      setDigestError("");
      try {
        await request(`/agents/decisions/${decision.id}/revert`, token, {
          method: "POST",
          body: JSON.stringify({}),
        });
        setDigest((current) =>
          current
            ? {
                ...current,
                decisions: current.decisions.map((d) =>
                  d.id === decision.id
                    ? { ...d, reverted: true, reverted_by: "admin" }
                    : d,
                ),
              }
            : current,
        );
        setAutonomyNotice(
          `Decisión «${decision.action_label ?? decision.action_type}» revertida.`,
        );
      } catch (err) {
        setDigestError(
          messageFrom(err, "No se pudo revertir la decisión del agente."),
        );
      } finally {
        setReverting("");
      }
    },
    [token],
  );

  const reload = useCallback(async () => {
    // Una sola generación para todos los bloques: si arranca un reload más
    // nuevo (StrictMode, refreshRevision), las respuestas antiguas se
    // descartan; si no, todas las comprobaciones pasan (una única captura,
    // sin contador compartido que se mueva entre awaits secuenciales).
    const generation = ++requestRevision.current;
    const stale = () => generation !== requestRevision.current;
    setLoading(true);
    setError("");
    try {
      const data = await request<{ status: string; agents: AgentDefinition[] }>(
        "/agents",
        token,
      );
      if (!stale()) {
        setAgents(Array.isArray(data.agents) ? data.agents : []);
      }
    } catch (err) {
      if (!stale()) {
        setAgents([]);
        setError(messageFrom(err, "No se pudieron cargar los agentes."));
      }
    } finally {
      setLoading(false);
    }
    setSupervisionLoading(true);
    setSupervisionError("");
    try {
      const data = await request<{
        status: string;
        agents: AgentSupervision[];
      }>("/agents/supervision", token);
      if (!stale()) {
        setSupervision(Array.isArray(data.agents) ? data.agents : []);
      }
    } catch (err) {
      if (!stale()) {
        setSupervision([]);
        setSupervisionError(
          messageFrom(err, "No se pudo cargar la supervisión de agentes."),
        );
      }
    } finally {
      setSupervisionLoading(false);
    }
    setAutonomyLoading(true);
    setAutonomyError("");
    try {
      const data = await request<{
        agents: AutonomyAgent[];
        safe_actions?: Record<string, string>;
      }>("/agents/autonomy", token);
      if (!stale()) {
        const agents = Array.isArray(data.agents) ? data.agents : [];
        setAutonomy(agents);
        setSafeActions(data.safe_actions ?? {});
        setAutonomyDraft((current) => {
          const draft: Record<string, AutonomyAgent> = {};
          for (const agent of agents) draft[agent.agent_id] = agent;
          return { ...current, ...draft };
        });
      }
    } catch (err) {
      if (!stale()) {
        setAutonomy([]);
        setAutonomyError(
          messageFrom(err, "No se pudo cargar la configuración de autonomía."),
        );
      }
    } finally {
      setAutonomyLoading(false);
    }
    setDigestError("");
    try {
      const data = await request<AgentDigest>("/agents/digest?days=7", token);
      if (!stale()) {
        setDigest(data);
      }
    } catch (err) {
      if (!stale()) {
        setDigest(null);
        setDigestError(
          messageFrom(err, "No se pudo cargar el digest de decisiones."),
        );
      }
    }
  }, [token]);

  useEffect(() => {
    void reload();
    return () => {
      requestRevision.current += 1;
    };
  }, [refreshRevision, reload]);

  function updateForm(field: keyof typeof form, value: string) {
    createKey.current = "";
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function createAgent(event: FormEvent) {
    event.preventDefault();
    if (!canWrite || mutating) return;
    const budget = Number(form.monthly_budget_usd);
    if (!Number.isFinite(budget) || budget < 0) {
      setMutationError(
        "El presupuesto mensual debe ser un número igual o superior a cero.",
      );
      return;
    }
    const allowedTools = form.allowed_tools
      .split(",")
      .map((tool) => tool.trim())
      .filter(Boolean);
    createKey.current ||= operationKey("agent-create");
    setMutating("create");
    setNotice("");
    setMutationError("");
    try {
      const result = await request<{ status: string; agent: AgentDefinition }>(
        "/agents",
        token,
        {
          method: "POST",
          headers: { "Idempotency-Key": createKey.current },
          body: JSON.stringify({
            agent_id: form.agent_id.trim(),
            name: form.name.trim(),
            purpose: form.purpose.trim(),
            prompt: form.prompt.trim(),
            autonomy_level: "Fase_D_Venta_Asistida",
            allowed_tools: allowedTools,
            primary_model: "standard",
            fallback_model: "local",
            monthly_budget_usd: budget,
            status: "draft",
          }),
        },
      );
      setNotice(
        `Agente ${result.agent.agent_id} persistido como borrador v${result.agent.version ?? 1}. No puede ejecutarse hasta su aprobación.`,
      );
      setForm({
        agent_id: "",
        name: "",
        purpose: "",
        prompt: "",
        allowed_tools: "search_products",
        monthly_budget_usd: "20.00",
      });
      createKey.current = "";
      await reload();
    } catch (err) {
      setMutationError(messageFrom(err, "No se pudo guardar el agente."));
    } finally {
      setMutating("");
    }
  }

  async function requestActivation(agent: AgentDefinition) {
    if (
      !canWrite ||
      mutating ||
      !agent.persisted ||
      agent.version === undefined
    )
      return;
    setMutating(agent.agent_id);
    setNotice("");
    setMutationError("");
    try {
      await request(
        `/agents/${encodeURIComponent(agent.agent_id)}/request-activation`,
        token,
        {
          method: "POST",
          headers: {
            "If-Match": String(agent.version),
            "Idempotency-Key": versionedKey(
              "agent-activation",
              agent.agent_id,
              agent.version,
            ),
          },
          body: JSON.stringify({}),
        },
      );
      setNotice(
        `La activación de ${agent.agent_id} queda pendiente de aprobación humana; el agente aún no puede ejecutarse.`,
      );
      await reload();
    } catch (err) {
      setMutationError(messageFrom(err, "No se pudo solicitar la activación."));
    } finally {
      setMutating("");
    }
  }

  return (
    <section id="agentes" className="module-stack" aria-label="Agentes de IA">
      <div className="alert warning" role="status">
        Solo los agentes activos pueden ejecutarse. Guardar una definición crea
        siempre un borrador persistido y auditable.
      </div>
      {!canWrite && (
        <div className="alert info">
          Tu rol permite consultar definiciones, pero no crear ni solicitar
          activaciones.
        </div>
      )}
      <MutationFeedback notice={notice} error={mutationError} />
      <article className="panel">
        <ModuleHeading
          eyebrow="Registro real"
          title="Agentes de IA"
          count={agents.length}
          icon={<Bot size={20} />}
        />
        <LoadingOrError
          loading={loading}
          error={error}
          empty={agents.length === 0}
        />
        {agents.length > 0 && (
          <div className="resource-list agent-list">
            {agents.map((agent) => (
              <article className="resource-card" key={agent.agent_id}>
                <div>
                  <strong>{agent.name}</strong>
                  {agent.module_label && (
                    <span className="badge badge-blue">
                      {agent.module_label}
                    </span>
                  )}
                  <StatusBadge status={agent.status} />
                </div>
                <span>
                  {agent.agent_id}
                  {agent.persisted
                    ? ` · persistido · v${agent.version ?? "—"}`
                    : " · integrado"}
                </span>
                <p>{agent.purpose}</p>
                {agent.scope && <p className="muted">Alcance: {agent.scope}</p>}
                <details>
                  <summary>Ver configuración avanzada</summary>
                  <dl>
                    <div>
                      <dt>Autonomía</dt>
                      <dd>{agent.autonomy_level ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>Herramientas</dt>
                      <dd>
                        {Array.isArray(agent.allowed_tools) &&
                        agent.allowed_tools.length > 0
                          ? agent.allowed_tools.join(", ")
                          : "Ninguna"}
                      </dd>
                    </div>
                    <div>
                      <dt>Modelos</dt>
                      <dd>
                        {agent.primary_model ?? "—"} /{" "}
                        {agent.fallback_model ?? "—"}
                      </dd>
                    </div>
                    <div>
                      <dt>Presupuesto mensual</dt>
                      <dd>
                        {formatMoney(agent.monthly_budget_usd ?? 0, "USD")}
                      </dd>
                    </div>
                    {agent.prompt && (
                      <div>
                        <dt>Instrucción</dt>
                        <dd>{agent.prompt}</dd>
                      </div>
                    )}
                  </dl>
                </details>
                {canWrite &&
                  agent.persisted &&
                  agent.version !== undefined &&
                  ["draft", "inactive", "rejected"].includes(agent.status) && (
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={Boolean(mutating)}
                      onClick={() => void requestActivation(agent)}
                    >
                      {mutating === agent.agent_id
                        ? "Enviando…"
                        : "Solicitar activación"}
                    </button>
                  )}
              </article>
            ))}
          </div>
        )}
        {canWrite && (
          <details className="module-form-wrap">
            <summary>Crear nuevo agente (configuración avanzada)</summary>
            <form
              className="module-form"
              onSubmit={createAgent}
              aria-busy={mutating === "create"}
            >
              <h3>Nueva definición de agente</h3>
              <p className="form-help">
                El ID no puede coincidir con un agente integrado. Las
                herramientas se validan en el servidor.
              </p>
              <div className="import-grid">
                <label>
                  ID del agente
                  <input
                    required
                    pattern="[a-z][a-z0-9_-]{2,79}"
                    maxLength={80}
                    value={form.agent_id}
                    onChange={(event) =>
                      updateForm("agent_id", event.target.value)
                    }
                  />
                </label>
                <label>
                  Nombre
                  <input
                    required
                    minLength={3}
                    maxLength={160}
                    value={form.name}
                    onChange={(event) => updateForm("name", event.target.value)}
                  />
                </label>
                <label>
                  Presupuesto mensual (USD)
                  <input
                    required
                    type="number"
                    min={0}
                    step="0.01"
                    value={form.monthly_budget_usd}
                    onChange={(event) =>
                      updateForm("monthly_budget_usd", event.target.value)
                    }
                  />
                </label>
              </div>
              <label>
                Propósito
                <textarea
                  required
                  minLength={3}
                  maxLength={2000}
                  rows={3}
                  value={form.purpose}
                  onChange={(event) =>
                    updateForm("purpose", event.target.value)
                  }
                />
              </label>
              <label>
                Instrucción del sistema
                <textarea
                  required
                  minLength={3}
                  maxLength={20000}
                  rows={5}
                  value={form.prompt}
                  onChange={(event) => updateForm("prompt", event.target.value)}
                />
              </label>
              <label>
                Herramientas permitidas (separadas por coma)
                <input
                  maxLength={1000}
                  value={form.allowed_tools}
                  onChange={(event) =>
                    updateForm("allowed_tools", event.target.value)
                  }
                />
              </label>
              <button
                className="primary-button"
                type="submit"
                disabled={Boolean(mutating)}
              >
                {mutating === "create" ? "Guardando…" : "Guardar borrador"}
              </button>
            </form>
          </details>
        )}
      </article>
      <article className="panel">
        <ModuleHeading
          eyebrow="Mando único"
          title="Chat universal"
          icon={<Bot size={20} />}
        />
        <p className="muted">
          Pregunta en lenguaje natural: consulta datos reales de todos los
          módulos y prepara las acciones (follow-ups, pausar o activar
          automatizaciones) como propuestas que solo tienes que confirmar.
        </p>
        <CeoChat token={token} compact />
      </article>
      <article className="panel">
        <ModuleHeading
          eyebrow="Control empresarial"
          title="Autonomía por excepción"
          count={autonomy.length}
          icon={<Gauge size={20} />}
        />
        <p className="muted">
          Para cada agente, decide con un interruptor si{" "}
          <strong>puede actuar solo</strong> o si cada acción necesita tu
          aprobación. Lo que haga por su cuenta queda registrado en el digest
          diario, con opción de revertirlo.
        </p>
        {autonomyNotice && (
          <div className="alert success">{autonomyNotice}</div>
        )}
        {autonomyError && <div className="alert error">{autonomyError}</div>}
        {autonomyLoading ? (
          <p className="muted">Cargando autonomía…</p>
        ) : (
          <div className="resource-list agent-list">
            {autonomy.map((agent) => {
              const draft = autonomyDraft[agent.agent_id] ?? agent;
              const draftActions = draft.allowed_actions ?? [];
              const agentActions = agent.allowed_actions ?? [];
              const changed =
                draft.mode !== agent.mode ||
                draft.max_value_threshold !== agent.max_value_threshold ||
                draft.max_actions_per_day !== agent.max_actions_per_day ||
                draft.notify_on_deviation_only !==
                  agent.notify_on_deviation_only ||
                draftActions.length !== agentActions.length ||
                draftActions.some((action) => !agentActions.includes(action));
              const autonomous = draft.mode === "autonomous";
              return (
                <article className="resource-card" key={agent.agent_id}>
                  <div className="autonomy-head">
                    <div>
                      <strong>{agent.name}</strong>
                      {agent.module_label && (
                        <span className="badge badge-blue">
                          {agent.module_label}
                        </span>
                      )}
                      <span
                        className={`badge ${
                          autonomous ? "badge-green" : "badge-orange"
                        }`}
                      >
                        {autonomous ? "actúa solo" : "pide aprobación"}
                      </span>
                    </div>
                    <span className="muted">{agent.agent_id}</span>
                  </div>
                  <div className="autonomy-simple">
                    <label className="autonomy-switch">
                      <input
                        type="checkbox"
                        checked={autonomous}
                        disabled={!canWrite}
                        onChange={(event) =>
                          setAutonomyDraft((current) => ({
                            ...current,
                            [agent.agent_id]: {
                              ...draft,
                              mode: event.target.checked
                                ? "autonomous"
                                : "manual",
                            },
                          }))
                        }
                      />
                      <span>¿Puede actuar solo?</span>
                    </label>
                    {autonomous && (
                      <label className="autonomy-limit">
                        Límite de acciones por día
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={draft.max_actions_per_day ?? 10}
                          disabled={!canWrite}
                          onChange={(event) =>
                            setAutonomyDraft((current) => ({
                              ...current,
                              [agent.agent_id]: {
                                ...draft,
                                max_actions_per_day:
                                  Number(event.target.value) || 0,
                              },
                            }))
                          }
                        />
                      </label>
                    )}
                    <button
                      type="button"
                      className="primary-button"
                      disabled={!changed || !canWrite}
                      onClick={() => void saveAutonomy(agent.agent_id)}
                    >
                      Guardar autonomía
                    </button>
                  </div>
                  <details className="autonomy-advanced">
                    <summary>
                      Configuración avanzada (umbral y acciones)
                    </summary>
                    <div className="autonomy-controls">
                      <label>
                        Umbral de valor (EUR)
                        <input
                          type="number"
                          min={0}
                          step={50}
                          value={draft.max_value_threshold}
                          disabled={!autonomous}
                          onChange={(event) =>
                            setAutonomyDraft((current) => ({
                              ...current,
                              [agent.agent_id]: {
                                ...draft,
                                max_value_threshold:
                                  Number(event.target.value) || 0,
                              },
                            }))
                          }
                        />
                      </label>
                      {Object.entries(safeActions).map(([actionKey, label]) => {
                        const checked = draftActions.includes(actionKey);
                        return (
                          <label className="autonomy-check" key={actionKey}>
                            <input
                              type="checkbox"
                              checked={checked}
                              disabled={!autonomous}
                              onChange={(event) => {
                                const next = event.target.checked;
                                setAutonomyDraft((current) => ({
                                  ...current,
                                  [agent.agent_id]: {
                                    ...draft,
                                    allowed_actions: next
                                      ? Array.from(
                                          new Set([...draftActions, actionKey]),
                                        )
                                      : draftActions.filter(
                                          (action) => action !== actionKey,
                                        ),
                                  },
                                }));
                              }}
                            />{" "}
                            {label}
                          </label>
                        );
                      })}
                      <label className="autonomy-check">
                        <input
                          type="checkbox"
                          checked={draft.notify_on_deviation_only}
                          disabled={!autonomous}
                          onChange={(event) =>
                            setAutonomyDraft((current) => ({
                              ...current,
                              [agent.agent_id]: {
                                ...draft,
                                notify_on_deviation_only: event.target.checked,
                              },
                            }))
                          }
                        />{" "}
                        Avisar solo si se desvía
                      </label>
                    </div>
                  </details>
                </article>
              );
            })}
          </div>
        )}
      </article>
      <article className="panel">
        <ModuleHeading
          eyebrow="Control empresarial"
          title="Digest de decisiones de los agentes"
          count={digest?.total_decisions ?? 0}
          icon={<ClipboardList size={20} />}
        />
        {digestError && <div className="alert error">{digestError}</div>}
        {!digest ? (
          <p className="muted">Cargando digest…</p>
        ) : (
          <>
            <div className="supervision-stats">
              <span className="badge badge-green">
                {digest.total_decisions} decisiones auto-ejecutadas
              </span>
              <span className="badge badge-orange">
                {digest.pending_human_approvals} pendientes de aprobación humana
              </span>
            </div>
            {digest.by_agent.length === 0 && digest.decisions.length === 0 ? (
              <p className="muted">
                Sin decisiones en los últimos {digest.window_days} días: los
                agentes no han ejecutado nada por su cuenta.
              </p>
            ) : (
              <>
                {digest.by_agent.length > 0 && (
                  <div className="digest-by-agent">
                    {digest.by_agent.map((bucket) => (
                      <span key={bucket.agent_id}>
                        <strong>{bucket.agent_label ?? bucket.agent_id}</strong>
                        : {bucket.total} decis.
                        {bucket.deviations > 0 && (
                          <span className="badge badge-red">
                            {bucket.deviations} desv.
                          </span>
                        )}
                        {bucket.reverted > 0 && (
                          <span className="badge badge-orange">
                            {bucket.reverted} revert.
                          </span>
                        )}
                      </span>
                    ))}
                  </div>
                )}
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Agente</th>
                      <th>Acción</th>
                      <th>Objetivo</th>
                      <th>Cuándo</th>
                      <th>Desviación</th>
                      <th>Revert</th>
                    </tr>
                  </thead>
                  <tbody>
                    {digest.decisions.map((decision) => (
                      <tr key={decision.id}>
                        <td>
                          <code>
                            {decision.agent_label ?? decision.agent_id}
                          </code>
                        </td>
                        <td>
                          <code>
                            {decision.action_label ?? decision.action_type}
                          </code>
                        </td>
                        <td className="muted">
                          {(() => {
                            const link =
                              TARGET_MODULE_LINKS[decision.target_kind ?? ""];
                            const label = (
                              decision.target_label ?? decision.target_key
                            ).slice(0, 60);
                            return link ? (
                              <a
                                href={`#${link.hash}`}
                                title={link.label}
                                onClick={(event) => {
                                  event.preventDefault();
                                  openTarget(
                                    decision.target_kind,
                                    decision.target_focus_id,
                                  );
                                }}
                              >
                                {label}
                              </a>
                            ) : (
                              label
                            );
                          })()}
                        </td>
                        <td className="muted">
                          {formatActivityAt(decision.executed_at)}
                        </td>
                        <td>
                          {decision.deviation ? (
                            <span
                              className="badge badge-red"
                              title={decision.deviation_reason ?? ""}
                            >
                              desviación
                            </span>
                          ) : (
                            <span className="badge badge-green">normal</span>
                          )}
                        </td>
                        <td>
                          {decision.reverted ? (
                            <span className="muted">
                              revertida{" "}
                              {decision.reverted_by
                                ? `por ${decision.reverted_by}`
                                : ""}
                            </span>
                          ) : (
                            <button
                              type="button"
                              className="danger-button"
                              disabled={!canWrite || reverting === decision.id}
                              onClick={() => void revertDecision(decision)}
                            >
                              {reverting === decision.id
                                ? "Revertiendo…"
                                : "Revertir"}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        )}
      </article>
      <article className="panel">
        <ModuleHeading
          eyebrow="Control empresarial"
          title="Supervisión por módulo"
          count={supervision.length}
          icon={<Activity size={20} />}
        />
        {supervisionError ? (
          <div className="alert error">{supervisionError}</div>
        ) : supervisionLoading ? (
          <p className="muted">Cargando supervisión…</p>
        ) : supervision.length === 0 ? (
          <p className="muted">Sin agentes que supervisar.</p>
        ) : (
          <details className="supervision-wrap">
            <summary>
              Ver supervisión técnica (llamadas, herramientas, auditoría)
            </summary>
            <div className="resource-list agent-list">
              {supervision.map((agent) => (
                <article className="resource-card" key={agent.agent_id}>
                  <div>
                    <strong>{agent.name}</strong>
                    {agent.module_label && (
                      <span className="badge badge-blue">
                        {agent.module_label}
                      </span>
                    )}
                    <StatusBadge status={agent.status} />
                  </div>
                  <span className="muted">
                    {agent.agent_id} · {agent.autonomy_level ?? "—"} ·{" "}
                    {formatActivityAt(agent.summary.last_activity_at)}
                  </span>
                  <p className="muted">Alcance: {agent.scope ?? "—"}</p>
                  <div className="supervision-stats">
                    <span className="badge badge-green">
                      {agent.summary.calls} llamadas
                    </span>
                    <span className="badge">✓ {agent.summary.success}</span>
                    <span className="badge badge-orange">
                      ✗ {agent.summary.denied}
                    </span>
                    <span className="badge badge-red">
                      ! {agent.summary.errors}
                    </span>
                    <span className="badge">
                      {agent.authorized_tools.length} tools autorizadas
                    </span>
                  </div>
                  <details>
                    <summary>Estado de las tools</summary>
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Herramienta</th>
                          <th>Kind</th>
                          <th>Acceso</th>
                          <th>Llamadas</th>
                          <th>✓</th>
                          <th>✗</th>
                          <th>!</th>
                          <th>Última</th>
                        </tr>
                      </thead>
                      <tbody>
                        {agent.tools.map((tool) => (
                          <tr key={tool.name}>
                            <td>
                              <code>{tool.name}</code>
                              {!tool.declared && (
                                <span className="badge badge-red">
                                  no declarada
                                </span>
                              )}
                            </td>
                            <td>
                              <span className="badge">{tool.kind}</span>
                            </td>
                            <td>
                              {tool.authorized ? (
                                <span className="badge badge-green">
                                  autorizada
                                </span>
                              ) : (
                                <span className="badge badge-orange">
                                  denegada
                                </span>
                              )}
                            </td>
                            <td>{tool.calls}</td>
                            <td>{tool.success}</td>
                            <td>{tool.denied}</td>
                            <td>{tool.errors}</td>
                            <td className="muted">
                              {tool.last_status ? (
                                <>
                                  {tool.last_status}{" "}
                                  {formatActivityAt(tool.last_at)}
                                </>
                              ) : (
                                "sin uso"
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </details>
                  <details>
                    <summary>Últimas actuaciones auditadas</summary>
                    {agent.recent_actions.length === 0 ? (
                      <p className="muted">
                        Sin actuaciones: el agente aún no ha invocado
                        herramientas.
                      </p>
                    ) : (
                      <ul className="supervision-actions">
                        {agent.recent_actions.map((action, index) => (
                          <li key={`${action.timestamp}-${index}`}>
                            <span
                              className={`badge ${
                                action.status === "success"
                                  ? "badge-green"
                                  : action.status === "denied"
                                    ? "badge-orange"
                                    : "badge-red"
                              }`}
                            >
                              {action.status}
                            </span>{" "}
                            <code>{action.tool}</code>{" "}
                            <span className="muted">
                              {formatActivityAt(action.timestamp)}
                            </span>
                            {action.detail && (
                              <p className="muted">{action.detail}</p>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </details>
                </article>
              ))}
            </div>
          </details>
        )}
      </article>
    </section>
  );
}
