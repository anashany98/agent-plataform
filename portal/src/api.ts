const DEFAULT_API_BASE = "/api/bridge";
const DEFAULT_TIMEOUT_MS = 20_000;

export const AUTH_EXPIRED_EVENT = "agent-platform:auth-expired";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function resolveApiBase(configuredPath?: string): string {
  const candidate = (configuredPath ?? DEFAULT_API_BASE).trim();
  if (
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("?") ||
    candidate.includes("#")
  ) {
    throw new Error(
      "VITE_API_BASE_PATH debe ser una ruta del mismo origen que empiece por '/'.",
    );
  }
  return candidate === "/" ? "" : candidate.replace(/\/+$/, "");
}

export const API_BASE = resolveApiBase(import.meta.env.VITE_API_BASE_PATH);

type ApiRequestInit = RequestInit & {
  token?: string;
  timeoutMs?: number;
  expireSessionOnUnauthorized?: boolean;
};

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) =>
          item && typeof item === "object" && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : "",
        )
        .filter(Boolean);
      if (messages.length > 0) return messages.join(". ");
    }
  }
  if (status === 401) return "La sesión no es válida o ha caducado.";
  if (status === 403) return "No tienes permiso para realizar esta operación.";
  if (status === 404) return "El recurso solicitado no está disponible.";
  if (status === 409)
    return "La operación entra en conflicto con el estado actual.";
  if (status === 429)
    return "Demasiadas solicitudes. Inténtalo de nuevo más tarde.";
  if (status >= 500) return "El servicio no está disponible temporalmente.";
  return "No se pudo completar la operación.";
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestInit = {},
): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("La ruta de API debe empezar por '/'.");
  }

  const {
    token,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    expireSessionOnUnauthorized = true,
    ...init
  } = options;
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (
    init.body !== undefined &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  const controller = new AbortController();
  let timedOut = false;
  const abortFromCaller = () => controller.abort();
  if (init.signal?.aborted) controller.abort();
  else init.signal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
      cache: init.cache ?? "no-store",
      credentials: init.credentials ?? "same-origin",
    });
  } catch (error) {
    if (timedOut) {
      throw new ApiError(
        "La operación tardó demasiado. Comprueba el estado del servicio e inténtalo de nuevo.",
      );
    }
    if (controller.signal.aborted) {
      throw new ApiError("La operación fue cancelada.");
    }
    throw new ApiError(
      error instanceof TypeError
        ? "No se pudo conectar con el servicio. Comprueba tu conexión e inténtalo de nuevo."
        : "Se produjo un error inesperado al contactar con el servicio.",
    );
  } finally {
    window.clearTimeout(timeoutId);
    init.signal?.removeEventListener("abort", abortFromCaller);
  }

  const rawBody = await response.text();
  let payload: unknown = {};
  if (rawBody) {
    try {
      payload = JSON.parse(rawBody) as unknown;
    } catch {
      payload = {};
    }
  }

  if (!response.ok) {
    if (response.status === 401 && token && expireSessionOnUnauthorized) {
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }
    throw new ApiError(errorMessage(payload, response.status), response.status);
  }
  return payload as T;
}
