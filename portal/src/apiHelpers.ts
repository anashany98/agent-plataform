/**
 * Envoltura tipada sobre `apiRequest` para las llamadas del portal.
 *
 * Extraída de `App.tsx`: inyecta el token de sesión y un timeout opcional.
 */

import { apiRequest } from "./api";

export async function api<T>(
  path: string,
  token: string,
  init?: RequestInit,
  timeoutMs?: number,
): Promise<T> {
  return apiRequest<T>(path, {
    ...init,
    token,
    timeoutMs,
  });
}
