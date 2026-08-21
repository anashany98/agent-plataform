# Guía: desactivar el modo pensamiento de Qwen3 en LM Studio y medir la mejora

> **Fecha:** 2026-08-19 · **LM Studio 0.4.19+2** · **Modelo:** `qwen/qwen3-14b`
> (también aplica a `qwen/qwen3.8-27b` y `qwen3-8b`).

## Por qué hacerlo

Qwen3 trae el **modo pensamiento activado por defecto**: antes de responder, el
modelo genera un razonamiento interno que se va íntegro a `reasoning_content`
mientras `content` permanece vacío. Consecuencias observadas en esta máquina:

- **Latencia ~2–5× mayor**: cada respuesta paga un razonamiento largo aunque la
  pregunta sea trivial («¿hay stock bajo?» razona cientos de caracteres antes de
  responder).
- **Respuestas vacías si el presupuesto no alcanza**: con
  `LLM_MAX_OUTPUT_TOKENS=1024` (el default) el razonamiento se comía todo el
  presupuesto y el CEO agent caía a su plantilla determinista. Hubo que subirlo
  a 2048 solo para que el `content` llegara a salir.
- **Fuga de markdown**: el razonamiento no se muestra, pero infla la generación.

Para el CEO agent — donde las decisiones son deterministas y el LLM solo redacta
— el modo pensamiento no aporta calidad perceptible y sí mucha latencia. La
comparativa `docs/LLM_MODEL_COMPARISON.md` ya muestra a Qwen3 14B 2,4× más
rápido que deepseek-r1:8b *con* el thinking puesto; sin él, la mejora es mayor.

## Cómo desactivarlo en la UI de LM Studio

En LM Studio 0.4.x el interruptor vive en el panel de inferencia del modelo
cargado (ruta confirmada en el bundle de la app 0.4.19):

1. Con el modelo **cargado** (p. ej. `qwen/qwen3-14b`), abre el panel derecho
   del chat → pestaña **Inference**.
2. Busca la sección **Reasoning** → apaga el interruptor **Enable Thinking**.
   (El texto exacto de la app: *"Use Inference → Reasoning → Enable Thinking."*)
3. **Recarga el modelo** para que el cambio se aplique: descárgalo desde el
   selector de modelo (el botón de apagado junto al modelo cargado) y vuelve a
   cargarlo. El ajuste se fija al cargar; por eso LM Studio ignora
   `chat_template_kwargs`/`enable_thinking` pasados por API por petición
   (probado con 5 variantes, 2026-08-19).

Alternativa rápida para una sola conversación: en el chat hay un botón
**Think** (icono de bombilla) junto al selector de modelo — pulsarlo alterna el
thinking de esa sesión. No es persistente como el ajuste de Inference.

### Si el interruptor no aparece

El toggle solo se muestra si la plantilla del modelo expone la variable
(`customFields.enableThinking` en el card del GGUF). El Qwen3 oficial sí la
expone (por eso el `content` sale vacío: el thinking está activo). Si en un
modelo concreto no aparece el toggle:

- **Ollama** (alternativa local): `ollama run qwen3:14b` y luego
  `/set parameter enable_thinking false`, o pasar
  `{"enable_thinking": false}` en la llamada a la API.
- El stack solo necesita un endpoint OpenAI-compatible; LM Studio y Ollama
  son intercambiables cambiando `CHEAP_LLM_PROVIDER`/`STANDARD_LLM_PROVIDER`
  y las URLs base en el `.env` (ver `.freebuff/run.md`).

## Verificar que ya no piensa

1. **Por API** (sin tocar el portal), contra LM Studio directamente:

   ```bash
   curl -s -m 180 http://localhost:1234/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model":"qwen/qwen3-14b","messages":[{"role":"user","content":"¿cómo van las ventas?"}],"max_tokens":512}' \
     | python -c "import json,sys; d=json.load(sys.stdin); m=d[\"choices\"][0][\"message\"]; print(\"reasoning:\", repr(m.get(\"reasoning_content\"))[:80]); print(\"content:\", m[\"content\"][:200])"
   ```

   Con el thinking **ON** verás `reasoning_content` lleno y `content` vacío
   (o cortado). Con el thinking **OFF**, `reasoning_content` viene vacío y
   `content` responde directamente.

2. **En el chat del portal**: pregunta algo en `http://localhost:5176/#chat`;
   si el thinking sigue activo, la respuesta tarda varios segundos más de lo
   normal y el primer token llega tarde. El indicador `· openai` del
   encabezado no cambia (sigue siendo el mismo modelo).

## Medir la mejora de latencia en el chat del CEO

El benchmark oficial mide la latencia de pared de `POST /ceo/chat`
(recopilación de datos + LLM + pulido) con el mismo set de 6 preguntas de
solo lectura:

```bash
cd agent-plataform

# 1) ANTES (thinking ON) — ya capturado el 2026-08-19:
python .freebuff/bench_ceo_models.py --label qwen3-14b-thinking-on \
  --out .freebuff/evidence_ceo_models_thinking_on.json
#   -> Media: 6,67 s (4,14–4,47 s en la ejecución previa del día)

# 2) Desactiva Enable Thinking en LM Studio y recarga el modelo (pasos de arriba).

# 3) DESPUÉS (thinking OFF):
python .freebuff/bench_ceo_models.py --label qwen3-14b-thinking-off \
  --out .freebuff/evidence_ceo_models_thinking_off.json

# 4) Comparar (por pregunta y media):
python -c "
import json
for tag in ('thinking_on','thinking_off'):
    d = json.load(open(f'.freebuff/evidence_ceo_models_{tag}.json'))
    rows = [(r['question'], r['latency_s']) for r in d['questions'] if r.get('latency_s')]
    print(tag, 'media %.2fs' % (sum(v for _, v in rows) / len(rows)))
    for q, v in rows: print('  %6.2fs  %s' % (v, q))
"
```

**Qué esperar:** con el thinking OFF la media debería bajar a ~1,5–3 s
(las preguntas triviales pasan de 1–5 s a <1 s; «¿qué hay que aprobar?»,
la más pesada, de ~24 s a ~4–8 s). La calidad de las respuestas no cambia
apreciablemente: el CEO agent ya redactaba respuestas concisas con los datos;
lo que se pierde es el razonamiento interno, no la fidelidad a los datos.

**Qué NO cambia:** la latencia del *gathering* (recopilación de datos local)
es idéntica en ambos casos; la diferencia es atribuible al LLM. Y el tope
`LLM_MAX_OUTPUT_TOKENS=2048` puede quedarse como está — con el thinking
apagado el `content` ya no compite con el razonamiento por el presupuesto.

## Notas

- El ajuste de Inference es **por modelo** y persiste entre sesiones de LM
  Studio; el botón **Think** del chat es por conversación.
- Tras recargar el modelo, LM Studio puede tardar unos segundos en volver a
  servirlo; el primer `curl` puede dar timeout mientras carga.
- Esta guía no toca el código del repo: solo la configuración local de LM
  Studio y la medición. El `.env.candidate-0815` (gitignored) sigue igual.
