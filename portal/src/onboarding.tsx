/**
 * Onboarding guiado (T-072): primera impresión para personas sin experiencia
 * técnica.
 *
 * - Al primer acceso (sin clave en localStorage) se muestra un asistente paso
 *   a paso que explica la landing, invita a probar 3 preguntas de ejemplo en
 *   el chat real y ofrece un «modo guiado»: mientras está activo, la barra
 *   lateral solo muestra Asistente y Resumen (los módulos aparecen al
 *   terminar o pulsando «Mostrar todos los módulos»).
 * - La preferencia se persiste en localStorage: una vez completado u omitido,
 *   no vuelve a aparecer en esa instalación/navegador.
 */

import { useState } from "react";
import { Sparkles } from "lucide-react";

export const ONBOARDING_STORAGE_KEY = "guided-onboarding";
export type OnboardingMode = "active" | "done";

export function getOnboardingMode(): OnboardingMode {
  try {
    return window.localStorage.getItem(ONBOARDING_STORAGE_KEY) === "done"
      ? "done"
      : "active";
  } catch {
    // Almacenamiento no disponible: no bloquear nunca el acceso.
    return "done";
  }
}

export function completeOnboarding(): void {
  try {
    window.localStorage.setItem(ONBOARDING_STORAGE_KEY, "done");
  } catch {
    // sin persistencia: el modo guiado se queda en memoria esta sesión
  }
}

/** Preguntas de ejemplo que se envían al chat real del Asistente. */
export const ONBOARDING_EXAMPLE_QUESTIONS = [
  "¿cómo van las ventas?",
  "¿qué hay que aprobar?",
  "¿hay stock bajo?",
] as const;

const STEP_WELCOME = 0;
const STEP_EXAMPLES = 1;
const STEP_GUIDED = 2;

type OnboardingOverlayProps = {
  /** Envía la pregunta de ejemplo al chat universal (CeoChat). */
  onAskExample: (question: string) => void;
  /** Completa el onboarding (persiste «done» y muestra todos los módulos). */
  onFinish: () => void;
  /** Cierra el overlay pero mantiene el modo guiado activo. */
  onContinueGuided: () => void;
};

export function OnboardingOverlay({
  onAskExample,
  onFinish,
  onContinueGuided,
}: OnboardingOverlayProps) {
  const [step, setStep] = useState(STEP_WELCOME);
  const [askedExample, setAskedExample] = useState<string | null>(null);

  function askExample(question: string) {
    setAskedExample(question);
    onAskExample(question);
    setStep(STEP_GUIDED);
  }

  return (
    <div
      className="onboarding-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
      aria-describedby="onboarding-description"
    >
      <div className="onboarding-card">
        <div className="onboarding-step-dots" aria-hidden="true">
          <span className={step === STEP_WELCOME ? "active" : ""} />
          <span className={step === STEP_EXAMPLES ? "active" : ""} />
          <span className={step === STEP_GUIDED ? "active" : ""} />
        </div>

        {step === STEP_WELCOME && (
          <>
            <div className="onboarding-icon" aria-hidden="true">
              <Sparkles size={22} />
            </div>
            <p className="onboarding-eyebrow">Primeros pasos · 1 de 3</p>
            <h2 id="onboarding-title">Tu empresa, en una conversación</h2>
            <p id="onboarding-description">
              Esta aplicación está diseñada para que{" "}
              <strong>una sola persona</strong> gestione casi toda una empresa
              con la ayuda de agentes de IA. Desde esta pantalla puedes
              preguntar cualquier cosa en lenguaje natural: cómo van las ventas,
              qué hay que aprobar o si falta stock.
            </p>
            <div className="onboarding-actions">
              <button
                type="button"
                className="primary-button"
                onClick={() => setStep(STEP_EXAMPLES)}
              >
                Siguiente
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={onFinish}
              >
                Omitir
              </button>
            </div>
          </>
        )}

        {step === STEP_EXAMPLES && (
          <>
            <div className="onboarding-icon" aria-hidden="true">
              <Sparkles size={22} />
            </div>
            <p className="onboarding-eyebrow">Primeros pasos · 2 de 3</p>
            <h2 id="onboarding-title">Pruébalo ahora mismo</h2>
            <p id="onboarding-description">
              Elige una pregunta de ejemplo. La enviaremos al asistente y verás
              la respuesta real con los datos de tu empresa.
            </p>
            <div className="onboarding-examples">
              {ONBOARDING_EXAMPLE_QUESTIONS.map((question) => (
                <button
                  key={question}
                  type="button"
                  className="secondary-button"
                  onClick={() => askExample(question)}
                >
                  {question}
                </button>
              ))}
            </div>
            <div className="onboarding-actions">
              <button
                type="button"
                className="primary-button"
                onClick={() => setStep(STEP_GUIDED)}
              >
                Continuar
              </button>
            </div>
          </>
        )}

        {step === STEP_GUIDED && (
          <>
            <div className="onboarding-icon" aria-hidden="true">
              <Sparkles size={22} />
            </div>
            <p className="onboarding-eyebrow">
              {askedExample ? "¡Bien hecho!" : "Primeros pasos · 3 de 3"}
            </p>
            <h2 id="onboarding-title">
              {askedExample
                ? "La respuesta ya está en el chat"
                : "Empieza con calma"}
            </h2>
            <p id="onboarding-description">
              {askedExample
                ? `Acabamos de preguntar «${askedExample}» al asistente. Puedes ver la respuesta en el chat de esta pantalla y seguir probando cuando quieras.`
                : "Mientras te familiarizas, solo verás Asistente y Hoy en el menú. El resto de módulos (clientes, productos, facturación…) aparecerán cuando termines o cuando los necesites."}
            </p>
            <div className="onboarding-actions">
              <button
                type="button"
                className="primary-button"
                onClick={onFinish}
              >
                Mostrar todos los módulos
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={onContinueGuided}
              >
                Seguir en modo guiado
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
