import { afterEach, beforeEach, expect } from "vitest";
import { cleanup } from "@testing-library/react";
import * as matchers from "vitest-axe/matchers";

expect.extend(matchers);

// axe consulta canvas para algunas reglas visuales; jsdom no implementa el
// contexto y escribe ruido en stderr. Mantener `null` conserva el fallback de
// axe sin ocultar excepciones de la aplicación.
Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
  configurable: true,
  value: () => null,
});

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  cleanup();
});
