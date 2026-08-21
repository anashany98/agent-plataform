/**
 * Entrada por voz (T-073): dictado al chat universal con Web Speech API.
 *
 * - Con SpeechRecognition disponible, el botón «Hablar» aparece; al dictar,
 *   la transcripción final rellena el input y el envío usa exactamente el
 *   mismo pipeline de intenciones (/ceo/chat).
 * - Error de permisos → mensaje amigable y el botón vuelve a estar parado.
 * - Sin soporte del navegador → el botón no se renderiza (fail-closed) y el
 *   chat sigue funcionando por teclado.
 */
import { beforeEach, expect, test } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CeoChat } from "./ceoChat";

type MockSpeechResult = {
  isFinal: boolean;
  transcript: string;
};

class FakeSpeechRecognition {
  lang = "";
  interimResults = false;
  maxAlternatives = 1;
  continuous = false;
  onstart: (() => void) | null = null;
  onresult:
    | ((event: {
        resultIndex: number;
        results: ArrayLike<{
          isFinal: boolean;
          0: { transcript: string };
        }>;
      }) => void)
    | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  started = false;
  start(): void {
    this.started = true;
    this.onstart?.();
  }
  stop(): void {
    this.started = false;
    this.onend?.();
  }
  abort(): void {
    this.started = false;
    this.onend?.();
  }
}

let fakeRecognition: FakeSpeechRecognition | null = null;

function installSpeechRecognition(enabled: boolean) {
  delete (window as unknown as Record<string, unknown>).SpeechRecognition;
  delete (
    window as unknown as Record<string, unknown>
  ).webkitSpeechRecognition;
  if (!enabled) return;
  fakeRecognition = new FakeSpeechRecognition();
  (window as unknown as { SpeechRecognition: typeof FakeSpeechRecognition })
    .SpeechRecognition = class extends FakeSpeechRecognition {
    constructor() {
      super();
      fakeRecognition = this;
    }
  };
}

function deliverFinal(transcript: string) {
  fakeRecognition?.onresult?.({
    resultIndex: 0,
    results: [{ isFinal: true, 0: { transcript } }],
  });
}

function mockChatApi() {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return new Response(
      JSON.stringify({
        answer: "Respuesta del asistente.",
        intent: "sales_summary",
        intent_label: "resumen de ventas",
        provider: "ollama",
        proposals: [],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }) as typeof fetch;
  return calls;
}

beforeEach(() => {
  window.localStorage.removeItem("ceo-conversation-id");
  installSpeechRecognition(true);
});

test("el botón de voz dicta al input y el envío usa el mismo pipeline", async () => {
  const calls = mockChatApi();
  render(<CeoChat token="token-test" />);

  const mic = screen.getByRole("button", { name: "Hablar" });
  expect(mic.getAttribute("aria-pressed")).toBe("false");

  await userEvent.click(mic);
  expect(
    screen.getByRole("button", { name: "Detener la escucha" }),
  ).toBeTruthy();
  expect(mic.getAttribute("aria-pressed")).toBe("true");

  deliverFinal("¿cómo van las ventas?");
  fakeRecognition?.stop();

  const input = screen.getByLabelText(
    "Mensaje para el asistente",
  ) as HTMLInputElement;
  await waitFor(() => {
    expect(input.value).toContain("¿cómo van las ventas?");
  });

  await userEvent.click(screen.getByRole("button", { name: "Enviar" }));
  await waitFor(() => {
    const posted = calls.find(
      (call) => call.url.includes("/ceo/chat") && call.init?.method === "POST",
    );
    expect(posted).toBeTruthy();
    const body = JSON.parse(String(posted?.init?.body)) as { message: string };
    expect(body.message).toBe("¿cómo van las ventas?");
  });
});

test("el dictado acumula frases sucesivas en el mismo mensaje", async () => {
  mockChatApi();
  render(<CeoChat token="token-test" />);

  await userEvent.click(screen.getByRole("button", { name: "Hablar" }));
  deliverFinal("muestra las automatizaciones");
  deliverFinal("y pausa el sync");
  fakeRecognition?.stop();

  const input = screen.getByLabelText(
    "Mensaje para el asistente",
  ) as HTMLInputElement;
  await waitFor(() => {
    expect(input.value).toContain("muestra las automatizaciones y pausa el sync");
  });
});

test("un error de permisos muestra un mensaje amigable y deja de escuchar", async () => {
  mockChatApi();
  render(<CeoChat token="token-test" />);

  await userEvent.click(screen.getByRole("button", { name: "Hablar" }));
  fakeRecognition?.onerror?.({ error: "not-allowed" });

  expect(
    await screen.findByText(/No se pudo usar el micrófono/),
  ).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Hablar" }),
  ).toBeTruthy();
});

test("sin reconocimiento de voz el botón no aparece y el teclado funciona", async () => {
  installSpeechRecognition(false);
  const calls = mockChatApi();
  render(<CeoChat token="token-test" />);

  expect(screen.queryByRole("button", { name: "Hablar" })).toBeNull();

  const input = screen.getByLabelText("Mensaje para el asistente");
  await userEvent.type(input, "estado de los agentes");
  await userEvent.click(screen.getByRole("button", { name: "Enviar" }));
  await waitFor(() => {
    expect(
      calls.some(
        (call) => call.url.includes("/ceo/chat") && call.init?.method === "POST",
      ),
    ).toBe(true);
  });
});

test("detener la escucha con el botón corta el reconocimiento", async () => {
  mockChatApi();
  render(<CeoChat token="token-test" />);

  await userEvent.click(screen.getByRole("button", { name: "Hablar" }));
  expect(fakeRecognition?.started).toBe(true);

  await userEvent.click(
    screen.getByRole("button", { name: "Detener la escucha" }),
  );
  expect(fakeRecognition?.started).toBe(false);
  expect(
    screen.getByRole("button", { name: "Hablar" }),
  ).toBeTruthy();
});
