/**
 * Sección Usuarios: control de acceso y color de acento de la instalación.
 *
 * Extraída de `App.tsx`; el acento vive en el componente raíz y esta sección
 * lo edita a través de `onAccentChange`.
 */

import { useEffect, useState } from "react";
import { api } from "../apiHelpers";
import { roleLabel } from "../appFormat";
import { ACCENT_PRESETS, DEFAULT_ACCENT, type UserRow } from "../appTypes";

export function UsersSection({
  token,
  refreshRevision,
  accent,
  onAccentChange,
}: {
  token: string;
  refreshRevision: number;
  accent: string;
  onAccentChange: (accent: string) => void;
}) {
  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [error, setError] = useState("");
  const [draftAccent, setDraftAccent] = useState(accent);
  const [savingAccent, setSavingAccent] = useState(false);
  const [accentNotice, setAccentNotice] = useState("");
  const [accentError, setAccentError] = useState("");

  useEffect(() => {
    setDraftAccent(accent);
  }, [accent]);

  async function saveAccent() {
    const value = draftAccent.trim().toLowerCase();
    if (!/^#[0-9a-f]{6}$/.test(value)) {
      setAccentError(
        "El color debe tener formato #RRGGBB (por ejemplo #246bfd).",
      );
      return;
    }
    setSavingAccent(true);
    setAccentError("");
    setAccentNotice("");
    try {
      await api<{ accent_color: string }>("/appearance/settings", token, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accent_color: value }),
      });
      onAccentChange(value);
      localStorage.setItem("accent", value);
      setAccentNotice("Color de acento actualizado para toda la instalación.");
    } catch (err) {
      setAccentError(
        err instanceof Error ? err.message : "No se pudo guardar el color.",
      );
    } finally {
      setSavingAccent(false);
    }
  }

  async function resetAccent() {
    setDraftAccent(DEFAULT_ACCENT);
    setAccentError("");
    setAccentNotice("");
    setSavingAccent(true);
    try {
      await api<{ accent_color: string }>("/appearance/settings", token, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accent_color: DEFAULT_ACCENT }),
      });
      onAccentChange(DEFAULT_ACCENT);
      localStorage.setItem("accent", DEFAULT_ACCENT);
      setAccentNotice("Color de acento restablecido al azul por defecto.");
    } catch (err) {
      setAccentError(
        err instanceof Error ? err.message : "No se pudo restablecer el color.",
      );
    } finally {
      setSavingAccent(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setError("");
    api<UserRow[]>("/users", token)
      .then((data) => {
        if (!cancelled) {
          setRows(data);
          setError("");
        }
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error
              ? err.message
              : "No se pudieron cargar los usuarios",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [refreshRevision, token]);

  return (
    <section id="usuarios" className="panel" aria-label="Usuarios y permisos">
      <div className="panel-heading">
        <div>
          <p>Control de acceso</p>
          <h2>Usuarios y permisos</h2>
        </div>
        <span className="counter">{rows?.length ?? 0}</span>
      </div>
      {error && (
        <div className="alert error" role="alert">
          {error}. Esta sección requiere rol administrador.
        </div>
      )}
      {!error && rows === null && (
        <div className="empty-state">Cargando usuarios…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="empty-state">No hay usuarios registrados.</div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Usuarios y permisos</caption>
            <thead>
              <tr>
                <th scope="col">Usuario</th>
                <th scope="col">Rol</th>
                <th scope="col">Activo</th>
                <th scope="col">Cambio de contraseña pendiente</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.username}</td>
                  <td>{roleLabel(row.role)}</td>
                  <td>{row.is_active ? "Sí" : "No"}</td>
                  <td>{row.must_change_password ? "Sí" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="appearance-panel">
        <div className="panel-heading">
          <div>
            <p>Apariencia</p>
            <h2>Color de acento de la instalación</h2>
          </div>
          <span
            className="accent-preview"
            style={{ background: draftAccent }}
            aria-hidden="true"
          />
        </div>
        <p className="form-help">
          El acento se aplica a toda la instalación (sidebar, KPIs, botones,
          tablas y supervisión) y es visible para todos los roles.
        </p>
        <div
          className="accent-palette"
          role="group"
          aria-label="Colores de acento"
        >
          {ACCENT_PRESETS.map((preset) => (
            <button
              type="button"
              key={preset}
              className={`accent-swatch${preset === draftAccent ? " selected" : ""}`}
              style={{ background: preset }}
              aria-label={`Usar acento ${preset}`}
              aria-pressed={preset === draftAccent}
              onClick={() => {
                setDraftAccent(preset);
                setAccentError("");
              }}
            />
          ))}
        </div>
        <label className="accent-hex">
          Color personalizado (hex)
          <input
            value={draftAccent}
            maxLength={7}
            onChange={(event) => {
              setDraftAccent(event.target.value);
              setAccentError("");
            }}
            aria-label="Color personalizado en hexadecimal"
          />
        </label>
        {accentNotice && <div className="alert info">{accentNotice}</div>}
        {accentError && (
          <div className="alert error" role="alert">
            {accentError}
          </div>
        )}
        <div className="actions">
          <button
            type="button"
            className="primary-button"
            disabled={savingAccent}
            onClick={() => void saveAccent()}
          >
            {savingAccent ? "Guardando…" : "Guardar acento"}
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={savingAccent}
            onClick={() => void resetAccent()}
          >
            Restablecer azul
          </button>
        </div>
      </div>
    </section>
  );
}
