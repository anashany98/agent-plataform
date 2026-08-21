import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { Mic, Square } from "lucide-react";
import { apiRequest } from "./api";

/**
 * Chat universal (T-071): superficie única desde la que una sola persona
 * gobierna la empresa — consulta datos reales (ventas, pipeline, leads,
 * actividades, aprobaciones, social, stock, agentes y automatizaciones) y
 * prepara las acciones (follow-ups, pausar/activar automatizaciones) como
 * propuestas que solo hay que confirmar.
 *
 * El id de conversación se persiste en localStorage, así que el asistente
 * recuerda el contexto incluso al cambiar de sección (la memoria vive en el
 * backend por conversación).
 */

type CeoMessage = {
  role: "client" | "assistant";
  content: string;
  meta?: string;
};

type CeoChatResponse = {
  answer: string;
  intent: string;
  intent_label: string;
  provider: string;
  proposals: Array<{ id: string }>;
};

type CeoChatProps = {
  token: string;
  compact?: boolean;
  suggestions?: string[];
};

const DEFAULT_SUGGESTIONS = [
  "¿cómo van las ventas?",
  "muestra las automatizaciones",
  "estado de los agentes",
  "¿qué hay que aprobar?",
  "haz follow-up a los leads fríos",
  "¿hay stock bajo?",
];

const CONVERSATION_STORAGE_KEY = "ceo-conversation-id";

// Web Speech API: TypeScript no incluye SpeechRecognition en lib.dom.
// Declaramos solo el subconjunto que usamos y degradamos sin error en
// navegadores sin soporte (el botón simplemente no aparece).
type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  continuous: boolean;
  onstart: (() => void) | null;
  onresult:
    | ((event: {
        resultIndex: number;
        results: ArrayLike<{
          isFinal: boolean;
          0: { transcript: string };
        }>;
      }) => void)
    | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

function getSpeechRecognition(): SpeechRecognitionConstructor | null {
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function loadConversationId(): string {
  try {
    return (
      window.localStorage.getItem(CONVERSATION_STORAGE_KEY) ??
      `ceo-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
    );
  } catch {
    return `ceo-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }
}

export type CeoChatHandle = {
  /** Envía un mensaje al asistente (usado por el onboarding guiado). */
  send: (text: string) => void;
};

export const CeoChat = forwardRef<CeoChatHandle, CeoChatProps>(function CeoChat(
  { token, compact = false, suggestions = DEFAULT_SUGGESTIONS }: CeoChatProps,
  ref,
) {
  const [messages, setMessages] = useState<CeoMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const conversationRef = useRef<string>("");
  const logRef = useRef<HTMLDivElement | null>(null);
  const sendRef = useRef<(text?: string) => void>(() => undefined);
  const recognizerRef = useRef<SpeechRecognitionLike | null>(null);
  const voiceSupported = getSpeechRecognition() !== null;

  useEffect(() => {
    return () => {
      // Al desmontar, corta el reconocimiento en curso (evita fugas).
      recognizerRef.current?.abort();
    };
  }, []);

  useImperativeHandle(ref, () => ({
    send: (text: string) => sendRef.current(text),
  }));

  useEffect(() => {
    conversationRef.current = loadConversationId();
    try {
      window.localStorage.setItem(
        CONVERSATION_STORAGE_KEY,
        conversationRef.current,
      );
    } catch {
      // almacenamiento no disponible: la conversación sigue siendo efímera
    }
  }, []);

  useEffect(() => {
    if (!messages.length) return;
    // jsdom (tests) no implementa scrollTo: degrada sin error.
    logRef.current?.scrollTo?.({
      top: logRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const send = useCallback(
    async (text?: string) => {
      const message = (text ?? draft).trim();
      if (!message || sending) return;
      if (!conversationRef.current)
        conversationRef.current = loadConversationId();
      setMessages((current) => [
        ...current,
        { role: "client", content: message },
      ]);
      setDraft("");
      setSending(true);
      setError("");
      try {
        const data = await apiRequest<CeoChatResponse>("/ceo/chat", {
          token,
          method: "POST",
          body: JSON.stringify({
            message,
            conversation_id: conversationRef.current,
          }),
        });
        const meta = data.proposals.length
          ? `Propuesta: ${data.intent_label} · ${data.proposals.length} pendiente(s) de aprobación`
          : `${data.intent_label} · ${data.provider}`;
        setMessages((current) => [
          ...current,
          { role: "assistant", content: data.answer, meta },
        ]);
      } catch (err) {
        setError(messageFrom(err, "No se pudo conectar con el asistente."));
      } finally {
        setSending(false);
      }
    },
    [draft, sending, token],
  );
  // La ref siempre apunta al envío actual (evita capturas obsoletas).
  sendRef.current = send;

  function stopVoice(): void {
    recognizerRef.current?.stop();
    recognizerRef.current = null;
    setListening(false);
  }

  function toggleVoice(): void {
    if (listening) {
      stopVoice();
      return;
    }
    const Constructor = getSpeechRecognition();
    if (!Constructor) {
      setVoiceError(
        "Tu navegador no soporta la entrada por voz. Puedes escribir la pregunta normalmente.",
      );
      return;
    }
    setVoiceError("");
    const recognizer = new Constructor();
    recognizer.lang = "es-ES";
    recognizer.interimResults = true;
    recognizer.maxAlternatives = 1;
    recognizer.continuous = false;
    recognizer.onstart = () => setListening(true);
    recognizer.onresult = (event) => {
      // Acumula solo las transcripciones finales (el usuario puede corregir
      // el texto en el input antes de enviar; el pipeline de intenciones es
      // el mismo que el tecleado).
      let transcript = "";
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) transcript += result[0].transcript;
      }
      if (transcript.trim()) {
        setDraft((current) =>
          current.trim()
            ? `${current.trim()} ${transcript.trim()}`
            : transcript,
        );
      }
    };
    recognizer.onerror = (event) => {
      recognizerRef.current = null;
      setListening(false);
      const messages: Record<string, string> = {
        "not-allowed":
          "No se pudo usar el micrófono: revisa los permisos del navegador.",
        "service-not-allowed": "El navegador bloqueó el acceso al micrófono.",
        "no-speech":
          "No se detectó voz. Inténtalo de nuevo o escribe la pregunta.",
        network: "El reconocimiento de voz no está disponible sin conexión.",
      };
      setVoiceError(
        messages[event.error] ??
          "No se pudo reconocer la voz. Inténtalo de nuevo o escribe la pregunta.",
      );
    };
    recognizer.onend = () => {
      recognizerRef.current = null;
      setListening(false);
    };
    recognizerRef.current = recognizer;
    try {
      recognizer.start();
    } catch {
      setVoiceError(
        "No se pudo iniciar el micrófono. Revisa los permisos del navegador.",
      );
      recognizerRef.current = null;
      setListening(false);
    }
  }

  return (
    <div className={compact ? "ceo-chat" : "ceo-chat ceo-chat-large"}>
      <div
        className="ceo-chat-log"
        ref={logRef}
        aria-live="polite"
        aria-label="Conversación con el asistente"
      >
        {messages.length === 0 ? (
          <p className="muted">
            Pregunta en lenguaje natural: «¿cómo van las ventas?», «muestra las
            automatizaciones», «estado de los agentes», «¿qué hay que aprobar?»
            o «pausa el sync de PrestaShop».
          </p>
        ) : (
          messages.map((entry, index) => (
            <div key={index} className={`ceo-chat-bubble ${entry.role}`}>
              <p>{entry.content}</p>
              {entry.meta && (
                <span className="ceo-chat-meta">{entry.meta}</span>
              )}
            </div>
          ))
        )}
        {sending && <p className="muted">Pensando…</p>}
      </div>
      {error && <div className="alert error">{error}</div>}
      <form
        className="ceo-chat-form"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="¿cómo van las ventas?"
          maxLength={4000}
          aria-label="Mensaje para el asistente"
        />
        {voiceSupported && (
          <button
            type="button"
            className={`voice-button${listening ? " listening" : ""}`}
            onClick={toggleVoice}
            disabled={sending}
            aria-label={listening ? "Detener la escucha" : "Hablar"}
            aria-pressed={listening}
            title={listening ? "Detener la escucha" : "Pregunta hablando"}
          >
            {listening ? <Square size={17} /> : <Mic size={17} />}
          </button>
        )}
        <button
          className="primary-button"
          type="submit"
          disabled={sending || !draft.trim()}
        >
          Enviar
        </button>
      </form>
      {voiceError && (
        <p className="ceo-chat-voice-error" role="status">
          {voiceError}
        </p>
      )}
      <div className="ceo-chat-suggestions">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            className="secondary-button"
            onClick={() => void send(suggestion)}
            disabled={sending}
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
});
