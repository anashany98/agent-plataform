/**
 * Pantallas de acceso y cambio de contraseña temporal.
 *
 * Extraídas de `App.tsx`; no dependen del estado de la aplicación, solo del
 * callback `onLogin`/`onComplete` que les pasa el componente raíz.
 */

import { FormEvent, useState } from "react";
import { apiRequest } from "../api";

export function Login({
  onLogin,
  notice,
}: {
  onLogin: (
    token: string,
    username: string,
    role: string,
    mustChangePassword: boolean,
  ) => void;
  notice?: string;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const data = await apiRequest<{
        access_token: string;
        username: string;
        role?: string;
        must_change_password?: boolean;
      }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
        expireSessionOnUnauthorized: false,
      });
      if (!data.access_token || !data.username) {
        throw new Error("El servidor devolvió una sesión incompleta.");
      }
      onLogin(
        data.access_token,
        data.username,
        data.role ?? "",
        Boolean(data.must_change_password),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error inesperado");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-card" aria-labelledby="login-title">
        <div className="brand-mark">AI</div>
        <h1 id="login-title">Plataforma de agentes IA</h1>
        <p>Accede al panel de control de tu instalación.</p>
        {notice && (
          <div className="alert info" role="status">
            {notice}
          </div>
        )}
        <form onSubmit={submit} aria-busy={loading}>
          <label>
            Usuario
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>
            Contraseña
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          <button type="submit" className="primary-button" disabled={loading}>
            {loading ? "Accediendo…" : "Acceder"}
          </button>
        </form>
      </section>
    </main>
  );
}

export function ChangePassword({
  token,
  onComplete,
  onLogout,
}: {
  token: string;
  onComplete: () => void;
  onLogout: () => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (newPassword !== confirmation) {
      setError("Las contraseñas nuevas no coinciden");
      return;
    }
    setLoading(true);
    try {
      await apiRequest("/auth/change-password", {
        token,
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
        expireSessionOnUnauthorized: false,
      });
      onComplete();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudo cambiar la contraseña",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-card" aria-labelledby="password-title">
        <div className="brand-mark">AI</div>
        <h1 id="password-title">Cambia la contraseña temporal</h1>
        <p>
          Por seguridad, debes crear una contraseña personal antes de acceder al
          panel.
        </p>
        <form onSubmit={submit} aria-busy={loading}>
          <label>
            Contraseña temporal
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <label>
            Nueva contraseña
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              minLength={12}
              required
            />
          </label>
          <label>
            Repite la nueva contraseña
            <input
              type="password"
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              autoComplete="new-password"
              minLength={12}
              required
            />
          </label>
          <p className="password-help">
            Mínimo 12 caracteres, con mayúscula, minúscula, número y símbolo.
          </p>
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          <button type="submit" className="primary-button" disabled={loading}>
            {loading ? "Guardando…" : "Cambiar contraseña"}
          </button>
          <button
            type="button"
            className="secondary-button full-width"
            onClick={onLogout}
          >
            Volver al acceso
          </button>
        </form>
      </section>
    </main>
  );
}
