import { FormEvent, useEffect, useState } from "react";
import { apiRequest } from "./api";

export type CustomFieldDefinition = {
  id: string;
  key: string;
  label: string;
  entity_type: string;
  field_type: string;
  options: string[] | null;
  required: boolean;
  visibility: string;
  position: number;
  is_active: boolean;
  created_at: string | null;
};

const FIELD_TYPES = ["text", "number", "date", "boolean", "select"] as const;
const ENTITY_TYPES = ["lead", "opportunity"] as const;
const VISIBILITIES = ["all", "operators", "admins"] as const;

const FIELD_TYPE_LABELS: Record<string, string> = {
  text: "Texto",
  number: "Número",
  date: "Fecha",
  boolean: "Sí/No",
  select: "Selección",
};

const ENTITY_LABELS: Record<string, string> = {
  lead: "Lead",
  opportunity: "Oportunidad",
};

const VISIBILITY_LABELS: Record<string, string> = {
  all: "Todos los roles",
  operators: "Operadores o superior",
  admins: "Solo administradores",
};

export function formatFieldValue(
  field: Pick<CustomFieldDefinition, "field_type">,
  value: unknown,
): string {
  if (value === null || value === undefined || value === "") return "—";
  if (field.field_type === "boolean") return value ? "Sí" : "No";
  if (field.field_type === "number") {
    return typeof value === "number" ? String(value) : String(value);
  }
  return String(value);
}

export function CustomFieldsSection({
  token,
  refreshRevision,
}: {
  token: string;
  refreshRevision: number;
}) {
  const [fields, setFields] = useState<CustomFieldDefinition[] | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionResult, setActionResult] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState("");
  const [editVisibility, setEditVisibility] = useState("all");
  const [editRequired, setEditRequired] = useState(false);
  // Formulario de alta.
  const [newKey, setNewKey] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [newEntity, setNewEntity] = useState<string>("lead");
  const [newType, setNewType] = useState<string>("text");
  const [newOptions, setNewOptions] = useState("");
  const [newVisibility, setNewVisibility] = useState("all");
  const [newRequired, setNewRequired] = useState(false);
  const [creating, setCreating] = useState(false);

  async function loadFields() {
    setError("");
    try {
      const data = await apiRequest<CustomFieldDefinition[]>("/custom-fields", {
        token,
      });
      setFields(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudieron cargar los campos",
      );
    }
  }

  useEffect(() => {
    void loadFields();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, refreshRevision]);

  function flash(message: string) {
    setActionResult(message);
    window.setTimeout(() => setActionResult(""), 4_000);
  }

  async function createField(event: FormEvent) {
    event.preventDefault();
    setActionError("");
    setCreating(true);
    try {
      const payload: Record<string, unknown> = {
        key: newKey.trim().toLowerCase(),
        label: newLabel.trim(),
        entity_type: newEntity,
        field_type: newType,
        visibility: newVisibility,
        required: newRequired,
      };
      if (newType === "select") {
        payload.options = newOptions
          .split(",")
          .map((option) => option.trim())
          .filter(Boolean);
      }
      await apiRequest<CustomFieldDefinition>("/custom-fields", {
        token,
        method: "POST",
        body: JSON.stringify(payload),
      });
      setNewKey("");
      setNewLabel("");
      setNewOptions("");
      setNewRequired(false);
      flash("Campo creado. Cambio auditado.");
      await loadFields();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo crear el campo",
      );
    } finally {
      setCreating(false);
    }
  }

  async function toggleActive(field: CustomFieldDefinition) {
    setActionError("");
    try {
      await apiRequest<CustomFieldDefinition>(`/custom-fields/${field.id}`, {
        token,
        method: "PATCH",
        body: JSON.stringify({ is_active: !field.is_active }),
      });
      flash(field.is_active ? "Campo desactivado." : "Campo activado.");
      await loadFields();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo cambiar el campo",
      );
    }
  }

  function startEdit(field: CustomFieldDefinition) {
    setEditingId(field.id);
    setEditLabel(field.label);
    setEditVisibility(field.visibility);
    setEditRequired(field.required);
  }

  async function saveEdit(field: CustomFieldDefinition) {
    setActionError("");
    try {
      await apiRequest<CustomFieldDefinition>(`/custom-fields/${field.id}`, {
        token,
        method: "PATCH",
        body: JSON.stringify({
          label: editLabel.trim(),
          visibility: editVisibility,
          required: editRequired,
        }),
      });
      setEditingId(null);
      flash("Campo actualizado. Cambio auditado.");
      await loadFields();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "No se pudo guardar el campo",
      );
    }
  }

  return (
    <section
      id="custom-fields"
      className="panel"
      aria-label="Campos personalizados"
    >
      <div className="panel-heading">
        <div>
          <p>CRM local · P1-c</p>
          <h2>Campos personalizados</h2>
        </div>
        <span className="counter">{fields?.length ?? 0} activos</span>
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {actionError && (
        <div className="alert error" role="alert">
          {actionError}
        </div>
      )}
      {actionResult && (
        <div className="alert info" role="status">
          {actionResult}
        </div>
      )}
      {!error && fields === null && (
        <div className="empty-state">Cargando campos…</div>
      )}

      {fields !== null && (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">
              Definiciones de campos personalizados
            </caption>
            <thead>
              <tr>
                <th scope="col">Clave</th>
                <th scope="col">Etiqueta</th>
                <th scope="col">Entidad</th>
                <th scope="col">Tipo</th>
                <th scope="col">Visibilidad</th>
                <th scope="col">Obligatorio</th>
                <th scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {fields.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="empty-state">
                      Aún no hay campos personalizados. Crea el primero con el
                      formulario.
                    </div>
                  </td>
                </tr>
              )}
              {fields.map((field) => (
                <tr key={field.id}>
                  <td>
                    <code>{field.key}</code>
                  </td>
                  <td>
                    {editingId === field.id ? (
                      <input
                        aria-label={`Etiqueta de ${field.key}`}
                        value={editLabel}
                        maxLength={120}
                        onChange={(e) => setEditLabel(e.target.value)}
                      />
                    ) : (
                      field.label
                    )}
                  </td>
                  <td>
                    {ENTITY_LABELS[field.entity_type] ?? field.entity_type}
                  </td>
                  <td>
                    {FIELD_TYPE_LABELS[field.field_type] ?? field.field_type}
                    {field.options && field.options.length > 0
                      ? ` (${field.options.join(", ")})`
                      : ""}
                  </td>
                  <td>
                    {editingId === field.id ? (
                      <select
                        aria-label={`Visibilidad de ${field.key}`}
                        value={editVisibility}
                        onChange={(e) => setEditVisibility(e.target.value)}
                      >
                        {VISIBILITIES.map((visibility) => (
                          <option key={visibility} value={visibility}>
                            {VISIBILITY_LABELS[visibility]}
                          </option>
                        ))}
                      </select>
                    ) : (
                      (VISIBILITY_LABELS[field.visibility] ?? field.visibility)
                    )}
                  </td>
                  <td>
                    {editingId === field.id ? (
                      <input
                        type="checkbox"
                        aria-label={`Obligatorio ${field.key}`}
                        checked={editRequired}
                        onChange={(e) => setEditRequired(e.target.checked)}
                      />
                    ) : field.required ? (
                      "Sí"
                    ) : (
                      "No"
                    )}
                  </td>
                  <td className="queue-actions">
                    {editingId === field.id ? (
                      <>
                        <button
                          type="button"
                          className="primary-button"
                          onClick={() => void saveEdit(field)}
                        >
                          Guardar
                        </button>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => setEditingId(null)}
                        >
                          Cancelar
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => startEdit(field)}
                        >
                          Editar
                        </button>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => void toggleActive(field)}
                        >
                          {field.is_active ? "Desactivar" : "Activar"}
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form
        className="kanban-editor"
        onSubmit={(event) => void createField(event)}
      >
        <p>
          Nuevo campo. La clave es estable (minúsculas, números, guiones); la
          etiqueta es editable. Desactivar sustituye a borrar: los valores ya
          guardados se conservan.
        </p>
        <div className="kanban-editor-add">
          <input
            value={newKey}
            aria-label="Clave del nuevo campo"
            placeholder="clave_del_campo"
            maxLength={64}
            pattern="[a-z0-9_-]*"
            onChange={(e) => setNewKey(e.target.value.toLowerCase())}
          />
          <input
            value={newLabel}
            aria-label="Etiqueta del nuevo campo"
            placeholder="Etiqueta visible"
            maxLength={120}
            onChange={(e) => setNewLabel(e.target.value)}
          />
          <select
            aria-label="Entidad del nuevo campo"
            value={newEntity}
            onChange={(e) => setNewEntity(e.target.value)}
          >
            {ENTITY_TYPES.map((entity) => (
              <option key={entity} value={entity}>
                {ENTITY_LABELS[entity]}
              </option>
            ))}
          </select>
          <select
            aria-label="Tipo del nuevo campo"
            value={newType}
            onChange={(e) => setNewType(e.target.value)}
          >
            {FIELD_TYPES.map((type) => (
              <option key={type} value={type}>
                {FIELD_TYPE_LABELS[type]}
              </option>
            ))}
          </select>
          <select
            aria-label="Visibilidad del nuevo campo"
            value={newVisibility}
            onChange={(e) => setNewVisibility(e.target.value)}
          >
            {VISIBILITIES.map((visibility) => (
              <option key={visibility} value={visibility}>
                {VISIBILITY_LABELS[visibility]}
              </option>
            ))}
          </select>
        </div>
        {newType === "select" && (
          <div className="kanban-editor-add">
            <input
              value={newOptions}
              aria-label="Opciones del campo select separadas por comas"
              placeholder="Opciones separadas por comas: A, B, C"
              onChange={(e) => setNewOptions(e.target.value)}
            />
          </div>
        )}
        <div className="kanban-editor-save">
          <label>
            <input
              type="checkbox"
              checked={newRequired}
              onChange={(e) => setNewRequired(e.target.checked)}
            />{" "}
            Obligatorio
          </label>
          <button
            type="submit"
            className="primary-button"
            disabled={creating || !newKey.trim() || !newLabel.trim()}
          >
            {creating ? "Creando…" : "Crear campo"}
          </button>
        </div>
      </form>
    </section>
  );
}
