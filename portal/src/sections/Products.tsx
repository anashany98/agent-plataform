/**
 * Sección Catálogo: listado paginado, búsqueda léxica/semántica e importación
 * de productos locales.
 *
 * Extraída de `App.tsx`; recibe `token`, permisos e `refreshRevision` como
 * props y no conoce el estado global de la aplicación.
 */

import { FormEvent, useEffect, useState } from "react";
import { api } from "../apiHelpers";
import {
  formatDate,
  formatNumber,
  isDemoSource,
  newIdempotencyKey,
  tryFocusRow,
} from "../appFormat";
import type {
  ImportResponse,
  ProductRow,
  SemanticProductRow,
} from "../appTypes";

const CATALOG_PAGE_SIZE = 50;

type CatalogResponse = {
  items: ProductRow[];
  total: number;
  limit: number;
  offset: number;
};

function formatFreshness(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Fecha no disponible";
  const now = new Date();
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  );
  const startOfValue = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  );
  const days = Math.round(
    (startOfToday.getTime() - startOfValue.getTime()) / 86_400_000,
  );
  if (days <= 0) return "Hoy";
  if (days === 1) return "Ayer";
  if (days < 7) return `Hace ${days} días`;
  return formatDate(value);
}

export function ProductsSection({
  token,
  canImport,
  refreshRevision,
  active = true,
}: {
  token: string;
  canImport: boolean;
  refreshRevision: number;
  active?: boolean;
}) {
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [sortBy, setSortBy] = useState("name");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);
  const [importForm, setImportForm] = useState({
    sku: "",
    name: "",
    category: "Industrial",
    base_price: "0.00",
    stock_quantity: "0",
  });
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState("");
  const [importError, setImportError] = useState("");
  const [importPreview, setImportPreview] = useState<ImportResponse | null>(
    null,
  );
  const [importKey, setImportKey] = useState("");
  const [semanticQuery, setSemanticQuery] = useState("");
  const [semanticResults, setSemanticResults] = useState<
    SemanticProductRow[] | null
  >(null);
  const [semanticLoading, setSemanticLoading] = useState(false);
  const [semanticError, setSemanticError] = useState("");
  const [semanticDiscarded, setSemanticDiscarded] = useState<string[]>([]);
  const [semanticBlockedDemoCount, setSemanticBlockedDemoCount] = useState(0);
  const visibleRows =
    catalog?.items.filter((row) => !isDemoSource(row.source)) ?? null;
  const blockedDemoCount = catalog
    ? catalog.items.length - (visibleRows?.length ?? 0)
    : 0;

  // Deep-link desde el digest de agentes: enfoca y resalta el producto
  // objetivo (si está en la página actual del catálogo). La sección vive en
  // un div oculto y no se desmonta, por eso `active` también reintenta.
  useEffect(() => {
    if (!active) return;
    if (
      tryFocusRow(
        "portal_catalogo_focus",
        (id) => `[data-focus-id="${CSS.escape(id)}"]`,
      )
    ) {
      return;
    }
    const timer = window.setTimeout(() => {
      sessionStorage.removeItem("portal_catalogo_focus");
    }, 5_000);
    return () => window.clearTimeout(timer);
  }, [active, visibleRows]);
  const totalPages = Math.max(
    1,
    Math.ceil((catalog?.total ?? 0) / CATALOG_PAGE_SIZE),
  );
  const shownFrom = catalog ? catalog.offset + 1 : 0;
  const shownTo = catalog
    ? Math.min(catalog.offset + catalog.items.length, catalog.total)
    : 0;

  function catalogUrl(): string {
    const params = new URLSearchParams();
    if (appliedQuery.trim()) params.set("query", appliedQuery.trim());
    params.set("limit", String(CATALOG_PAGE_SIZE));
    params.set("offset", String(page * CATALOG_PAGE_SIZE));
    params.set("sort", sortBy);
    params.set("order", sortOrder);
    if (sourceFilter !== "all") params.set("source", sourceFilter);
    return `/catalog/products?${params.toString()}`;
  }

  async function loadCatalog(): Promise<void> {
    setCatalogError("");
    try {
      setCatalog(await api<CatalogResponse>(catalogUrl(), token));
    } catch (err) {
      setCatalogError(
        err instanceof Error ? err.message : "No se pudo cargar el catálogo",
      );
    }
  }

  function submitCatalogSearch(event: FormEvent) {
    event.preventDefault();
    setAppliedQuery(searchDraft.trim());
    setPage(0);
  }

  async function runSemanticSearch(event: FormEvent) {
    event.preventDefault();
    const query = semanticQuery.trim();
    if (query.length < 2) {
      setSemanticError("Escribe al menos 2 caracteres para buscar.");
      return;
    }
    setSemanticLoading(true);
    setSemanticError("");
    setSemanticResults(null);
    setSemanticDiscarded([]);
    setSemanticBlockedDemoCount(0);
    try {
      const data = await api<{
        query: string;
        products: SemanticProductRow[];
        discarded_tokens?: string[];
      }>(
        `/tools/products/semantic?query=${encodeURIComponent(query)}&top_k=10`,
        token,
      );
      const safeProducts = data.products.filter(
        (product) => !isDemoSource(product.source),
      );
      setSemanticResults(safeProducts);
      setSemanticBlockedDemoCount(data.products.length - safeProducts.length);
      setSemanticDiscarded(data.discarded_tokens ?? []);
    } catch (err) {
      setSemanticError(
        err instanceof Error ? err.message : "No se pudo buscar semánticamente",
      );
    } finally {
      setSemanticLoading(false);
    }
  }

  function semanticScoreClass(score: number) {
    if (score >= 0.6) return "score-high";
    if (score >= 0.4) return "score-mid";
    return "score-low";
  }

  function updateImportField(field: keyof typeof importForm, value: string) {
    setImportForm((current) => ({ ...current, [field]: value }));
    setImportPreview(null);
    setImportKey("");
    setImportResult("");
    setImportError("");
  }

  function productPayload() {
    const basePrice = Number(importForm.base_price);
    const stockQuantity = Number(importForm.stock_quantity);
    if (!importForm.sku.trim() || !importForm.name.trim()) {
      throw new Error("SKU y nombre son obligatorios.");
    }
    if (!Number.isFinite(basePrice) || basePrice < 0) {
      throw new Error("El precio debe ser un número igual o superior a cero.");
    }
    if (
      !Number.isInteger(stockQuantity) ||
      stockQuantity < 0 ||
      stockQuantity > 2_147_483_647
    ) {
      throw new Error("El stock debe ser un número entero válido.");
    }
    return {
      sku: importForm.sku.trim(),
      name: importForm.name.trim(),
      category: importForm.category.trim() || "General",
      base_price: basePrice,
      stock_quantity: stockQuantity,
      source: "local",
    };
  }

  function validationError(result: ImportResponse): string {
    const firstError = result.errors?.[0];
    return firstError
      ? `Fila ${firstError.row}: ${firstError.error}`
      : "El servidor rechazó los datos del producto.";
  }

  async function previewProduct(event: FormEvent) {
    event.preventDefault();
    setImporting(true);
    setImportResult("");
    setImportError("");
    setImportPreview(null);
    try {
      const payload = productPayload();
      const result = await api<ImportResponse>(
        "/import/products",
        token,
        {
          method: "POST",
          body: JSON.stringify({
            items: [payload],
            dry_run: true,
          }),
        },
        60_000,
      );
      if (result.status !== "dry_run" || (result.invalid_rows ?? 0) > 0) {
        throw new Error(validationError(result));
      }
      setImportPreview(result);
      setImportKey(newIdempotencyKey());
      setImportResult(
        "Validación correcta. Revisa los datos antes de confirmar.",
      );
    } catch (err) {
      setImportError(
        err instanceof Error ? err.message : "No se pudo validar el producto",
      );
    } finally {
      setImporting(false);
    }
  }

  async function confirmProductImport() {
    if (!importPreview || !importKey) return;
    setImporting(true);
    setImportError("");
    try {
      const payload = productPayload();
      const result = await api<ImportResponse>(
        "/import/products",
        token,
        {
          method: "POST",
          headers: { "Idempotency-Key": importKey },
          body: JSON.stringify({ items: [payload], dry_run: false }),
        },
        120_000,
      );
      if (result.status === "processing") {
        setImportResult(
          "La importación ya está en proceso. Conserva esta pantalla y vuelve a intentarlo.",
        );
        return;
      }
      if (result.status !== "success") {
        throw new Error(validationError(result));
      }
      setImportResult(
        `Producto importado correctamente (${result.imported_count ?? 1}).`,
      );
      setImportPreview(null);
      setImportKey("");
      setImportForm({
        sku: "",
        name: "",
        category: "Industrial",
        base_price: "0.00",
        stock_quantity: "0",
      });
      await loadCatalog();
      setCatalogError("");
    } catch (err) {
      setImportError(
        err instanceof Error ? err.message : "No se pudo importar",
      );
    } finally {
      setImporting(false);
    }
  }

  useEffect(() => {
    void loadCatalog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    refreshRevision,
    token,
    appliedQuery,
    sourceFilter,
    sortBy,
    sortOrder,
    page,
  ]);

  return (
    <section id="catalogo" className="panel" aria-label="Catálogo de productos">
      <div className="panel-heading">
        <div>
          <p>Catálogo</p>
          <h2>Productos</h2>
        </div>
        <span className="counter">{catalog?.total ?? 0}</span>
      </div>
      {catalogError && (
        <div className="alert error" role="alert">
          {catalogError}
        </div>
      )}
      {!catalogError && catalog === null && (
        <div className="empty-state">Cargando catálogo…</div>
      )}
      {!catalogError && blockedDemoCount > 0 && (
        <div className="alert warning" role="status">
          Se han ocultado {blockedDemoCount} registros con origen de prueba. No
          se muestran como catálogo real.
        </div>
      )}
      {!catalogError &&
        catalog !== null &&
        visibleRows !== null &&
        visibleRows.length === 0 && (
          <div className="empty-state">
            {appliedQuery || sourceFilter !== "all"
              ? "Sin resultados con los filtros actuales."
              : "No hay productos disponibles en esta instalación."}
          </div>
        )}
      {!catalogError && visibleRows !== null && visibleRows.length > 0 && (
        <div className="catalog-toolbar">
          <form
            className="catalog-search"
            onSubmit={submitCatalogSearch}
            aria-label="Búsqueda del catálogo"
          >
            <input
              value={searchDraft}
              onChange={(e) => setSearchDraft(e.target.value)}
              placeholder="Buscar por nombre, SKU o categoría"
              aria-label="Buscar en el catálogo"
            />
            <button type="submit" className="primary-button">
              Buscar en catálogo
            </button>
          </form>
          <label className="catalog-filter">
            Origen
            <select
              value={sourceFilter}
              onChange={(e) => {
                setSourceFilter(e.target.value);
                setPage(0);
              }}
              aria-label="Filtrar catálogo por origen"
            >
              <option value="all">Todos</option>
              <option value="local">Local</option>
              <option value="import">Importado</option>
              <option value="prestashop">PrestaShop</option>
            </select>
          </label>
          <label className="catalog-filter">
            Ordenar por
            <select
              value={sortBy}
              onChange={(e) => {
                setSortBy(e.target.value);
                setPage(0);
              }}
              aria-label="Ordenar catálogo por"
            >
              <option value="name">Nombre</option>
              <option value="unit_price">Precio</option>
              <option value="available_stock">Stock</option>
              <option value="updated_at">Actualización</option>
            </select>
          </label>
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              setSortOrder((current) => (current === "asc" ? "desc" : "asc"));
              setPage(0);
            }}
            aria-label={
              sortOrder === "asc"
                ? "Cambiar a orden descendente"
                : "Cambiar a orden ascendente"
            }
          >
            {sortOrder === "asc" ? "Ascendente ↑" : "Descendente ↓"}
          </button>
        </div>
      )}
      {!catalogError && visibleRows !== null && visibleRows.length > 0 && (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Productos disponibles</caption>
            <thead>
              <tr>
                <th scope="col">Nombre</th>
                <th scope="col">SKU</th>
                <th scope="col">Categoría</th>
                <th scope="col">Precio unitario</th>
                <th scope="col">Stock disponible</th>
                <th scope="col">Origen</th>
                <th scope="col">Actualizado</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row) => (
                <tr key={row.id} data-focus-id={row.id}>
                  <td>{row.name}</td>
                  <td>{row.sku}</td>
                  <td>{row.category || "—"}</td>
                  <td>{formatNumber(row.unit_price)} €</td>
                  <td>{row.available_stock}</td>
                  <td>{row.source}</td>
                  <td title={formatDate(row.updated_at ?? null)}>
                    {formatFreshness(row.updated_at ?? null)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!catalogError && catalog !== null && catalog.total > 0 && (
        <div className="catalog-pagination">
          <span aria-live="polite">
            Mostrando {shownFrom}–{shownTo} de {catalog.total} productos
          </span>
          <div className="actions">
            <button
              type="button"
              className="secondary-button"
              disabled={page === 0}
              onClick={() => setPage((current) => Math.max(0, current - 1))}
            >
              Página anterior
            </button>
            <span>
              Página {page + 1} de {totalPages}
            </span>
            <button
              type="button"
              className="secondary-button"
              disabled={page + 1 >= totalPages}
              onClick={() =>
                setPage((current) => Math.min(totalPages - 1, current + 1))
              }
            >
              Página siguiente
            </button>
          </div>
        </div>
      )}

      <form
        className="semantic-search"
        onSubmit={(event) => void runSemanticSearch(event)}
        aria-label="Búsqueda semántica del catálogo"
      >
        <p>Búsqueda semántica del catálogo</p>
        <p className="semantic-hint">
          Encuentra productos por concepto aunque el nombre no contenga los
          términos. Los resultados solo aparecen cuando la indexación semántica
          está configurada.
        </p>
        <div className="semantic-row">
          <input
            value={semanticQuery}
            onChange={(e) => setSemanticQuery(e.target.value)}
            placeholder="p. ej. pantalla para jugar a videojuegos"
            aria-label="Consulta semántica"
          />
          <button className="primary-button" disabled={semanticLoading}>
            {semanticLoading ? "Buscando…" : "Buscar"}
          </button>
        </div>
        {!semanticError &&
          !semanticLoading &&
          semanticResults !== null &&
          semanticDiscarded.length > 0 && (
            <p className="semantic-discarded" aria-label="Tokens descartados">
              Tokens de 1–2 caracteres ignorados por el buscador léxico:{" "}
              {semanticDiscarded.map((t) => `“${t}”`).join(", ")}.
            </p>
          )}
        {!semanticError && semanticBlockedDemoCount > 0 && (
          <div className="alert warning" role="status">
            Se han ocultado {semanticBlockedDemoCount} resultados con origen de
            prueba.
          </div>
        )}
        {semanticError && (
          <div className="alert error" role="alert">
            {semanticError}
          </div>
        )}
        {!semanticError && semanticLoading && (
          <div className="empty-state">Buscando semánticamente…</div>
        )}
        {!semanticError &&
          !semanticLoading &&
          semanticResults !== null &&
          (semanticResults.length === 0 ? (
            <div className="empty-state">
              Sin coincidencias sobre el umbral. Si el catálogo todavía no está
              indexado, solicita la indexación a un administrador.
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <caption className="sr-only">
                  Resultados de la búsqueda semántica
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Nombre</th>
                    <th scope="col">SKU</th>
                    <th scope="col">Categoría</th>
                    <th scope="col">Precio unitario</th>
                    <th scope="col">Stock disponible</th>
                    <th scope="col">Origen</th>
                    <th scope="col">Similitud</th>
                  </tr>
                </thead>
                <tbody>
                  {semanticResults.map((row) => (
                    <tr key={row.id}>
                      <td>{row.name}</td>
                      <td>{row.sku}</td>
                      <td>{row.category || "—"}</td>
                      <td>{formatNumber(row.unit_price)} €</td>
                      <td>{row.available_stock}</td>
                      <td>{row.source}</td>
                      <td>
                        <span
                          className={`semantic-score ${semanticScoreClass(row.score)}`}
                        >
                          {(row.score * 100).toFixed(1)}%
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
      </form>

      {canImport && (
        <form
          className="import-form"
          onSubmit={(event) => void previewProduct(event)}
          aria-label="Importar producto"
          aria-busy={importing}
        >
          <p>Importar producto al catálogo local</p>
          <p className="form-help">
            El tipo de IVA se obtiene de la configuración fiscal del servidor.
            Primero se valida sin guardar; la importación requiere una
            confirmación separada.
          </p>
          <div className="import-grid">
            <label>
              SKU
              <input
                value={importForm.sku}
                onChange={(e) => updateImportField("sku", e.target.value)}
                autoComplete="off"
                required
              />
            </label>
            <label>
              Nombre
              <input
                value={importForm.name}
                onChange={(e) => updateImportField("name", e.target.value)}
                autoComplete="off"
                required
              />
            </label>
            <label>
              Categoría
              <input
                value={importForm.category}
                onChange={(e) => updateImportField("category", e.target.value)}
                autoComplete="off"
              />
            </label>
            <label>
              Precio unitario
              <input
                type="number"
                step="0.01"
                min="0"
                value={importForm.base_price}
                onChange={(e) =>
                  updateImportField("base_price", e.target.value)
                }
                required
              />
            </label>
            <label>
              Stock
              <input
                type="number"
                min="0"
                value={importForm.stock_quantity}
                onChange={(e) =>
                  updateImportField("stock_quantity", e.target.value)
                }
                required
              />
            </label>
            <button
              type="submit"
              className="primary-button"
              disabled={importing}
            >
              {importing ? "Validando…" : "Validar producto"}
            </button>
          </div>
          {importError && (
            <div className="alert error" role="alert">
              {importError}
            </div>
          )}
          {importResult && (
            <div className="alert info" role="status">
              {importResult}
            </div>
          )}
          {importPreview && (
            <div
              className="confirmation-card"
              role="group"
              aria-label="Confirmar importación"
            >
              <strong>Revisión final</strong>
              <span>
                {importForm.name.trim()} · SKU {importForm.sku.trim()} ·{" "}
                {formatNumber(Number(importForm.base_price))} € · stock{" "}
                {importForm.stock_quantity}
              </span>
              <div className="actions">
                <button
                  type="button"
                  className="success-button"
                  disabled={importing}
                  onClick={() => void confirmProductImport()}
                >
                  {importing ? "Importando…" : "Confirmar importación"}
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={importing}
                  onClick={() => {
                    setImportPreview(null);
                    setImportKey("");
                    setImportResult("");
                  }}
                >
                  Cancelar
                </button>
              </div>
            </div>
          )}
        </form>
      )}
    </section>
  );
}
