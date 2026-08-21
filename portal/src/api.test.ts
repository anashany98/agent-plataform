import { afterEach, expect, test, vi } from "vitest";
import { apiRequest, AUTH_EXPIRED_EVENT, resolveApiBase } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("la base de API solo admite rutas del mismo origen", () => {
  expect(resolveApiBase()).toBe("/api/bridge");
  expect(resolveApiBase("/bridge/")).toBe("/bridge");
  expect(() => resolveApiBase("https://api.example.com")).toThrow(
    "ruta del mismo origen",
  );
  expect(() => resolveApiBase("//api.example.com")).toThrow(
    "ruta del mismo origen",
  );
});

test("los errores de validación estructurados se muestran de forma útil", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: [{ loc: ["body", "name"], msg: "El nombre es obligatorio" }],
        }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );

  await expect(apiRequest("/validation")).rejects.toThrow(
    "El nombre es obligatorio",
  );
});

test("un 401 autenticado notifica la expiración de sesión", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Token revocado" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  const listener = vi.fn();
  window.addEventListener(AUTH_EXPIRED_EVENT, listener);

  await expect(
    apiRequest("/dashboard", { token: "token-caducado" }),
  ).rejects.toThrow("Token revocado");
  expect(listener).toHaveBeenCalledOnce();
  window.removeEventListener(AUTH_EXPIRED_EVENT, listener);
});
