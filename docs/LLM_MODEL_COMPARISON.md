# Comparativa LLM del CEO agent: Qwen3 14B vs deepseek-r1:8b

> **Fecha:** 2026-08-19 · **Entorno:** stack candidato de preview (bridge-api
> con `docker-compose.preview-code.yml`), PostgreSQL real, catálogo PrestaShop
> sincronizado. Evidencias crudas en `.freebuff/evidence_ceo_models_*.json`.

## Metodología

- **Mismo set de 6 preguntas de solo lectura** (las que usan el LLM para
  redactar): ventas, stock bajo, aprobaciones pendientes, estado de los
  agentes, automatizaciones y pipeline.
- **Mismo token** (1 login; el JWT no se invalida al recrear el contenedor),
  misma instalación, mismas variables (`LLM_MAX_OUTPUT_TOKENS=2048`,
  `LLM_REQUEST_TIMEOUT_SEC=120`).
- **Qwen3 14B** → LM Studio (`http://host.docker.internal:1234/v1`,
  `openai/qwen/qwen3-14b`). **deepseek-r1:8b** → Ollama
  (`http://host.docker.internal:11434`).
- Medición: **latencia de pared** de `POST /ceo/chat` (recopilación de datos
  local + llamada LLM + pulido). La recopilación es idéntica en ambos, así que
  la diferencia es atribuible al LLM.

## Latencia

| Pregunta | Qwen3 14B | deepseek-r1:8b |
|---|---|---|
| ¿cómo van las ventas? | 4,45 s | 15,75 s |
| ¿hay stock bajo? | 0,96 s | 3,64 s |
| ¿qué hay que aprobar? | 11,19 s | 6,35 s |
| estado de los agentes | 4,16 s | 14,82 s |
| muestra las automatizaciones | 1,88 s | 13,80 s |
| ¿cómo está el pipeline? | 4,17 s | 7,95 s |
| **Media (2 ejecuciones Qwen3)** | **4,14–4,47 s** | **10,38 s** |

**Qwen3 14B es ~2,4× más rápido de media.** La única inversión es
«¿qué hay que aprobar?» (11,2 s vs 6,4 s): el prompt de aprobaciones es el
más largo y Qwen3 razona más antes de agregar la respuesta.

## Calidad (6/6 preguntas comparadas)

| Dimensión | Qwen3 14B | deepseek-r1:8b |
|---|---|---|
| **Fidelidad a los datos** | 6/6 sin inventar cifras | 6/6 sin inventar cifras |
| **Fuga de razonamiento** | Ninguna | Ninguna |
| **Concisión** | Alta: responde en 1–3 líneas | Verbosa: repite datos y rellena |
| **Organización** | Agrupa (agentes en 3 líneas; aprobaciones por tipo con conteos) | Lista todo en bruto (9 agentes, IDs sueltos) |
| **Formato en el chat** | Usa `**negrita**`/`*cursiva*`/guiones (no se limpian en el chat) | Usa listas `*` (también se ven crudas) |
| **Localización** | Usa `€` y separador español («1104,2») | Mantiene «EUR» e ISO |

### Ejemplos representativos

**Ventas** — Qwen3 14B (4,45 s): «Las ventas tienen 25 oportunidades abiertas
por 1104.2 EUR, 0 ganadas, 1 perdida, win-rate 0.0%, ticket medio 43.25 EUR y
3 pedidos.» — r1:8b (15,75 s): la misma información con relleno («Hasta el
momento no hay ninguna ganada (0 EUR), pero sí hay una oportunidad que se
perdió…»).

**Estado de agentes** — Qwen3 14B agrupa los 9 agentes en 3 líneas (comercial
y CEO con propuestas, resto sin actividad); r1:8b lista los 9 con su módulo
duplicado entre paréntesis.

**Aprobaciones** — Ambos son exactos (29 pendientes); Qwen3 agrega por tipo
(2 facturas, 19 follow-ups, 8 otras), r1 lista los IDs sueltos.

## Veredicto y recomendación

- **Usar Qwen3 14B (LM Studio) como modelo por defecto**: mismo rigor
  factual que r1:8b, **2,4× más rápido** y respuestas más concisas y
  organizadas. En el candidato quedó configurado así.
- **Próximo paso de latencia**: esta comparativa es con el modo pensamiento
  de Qwen3 ACTIVO. Desactivarlo (Inference → Reasoning → Enable Thinking en
  la UI de LM Studio) acelera más las respuestas — guía y medición
  antes/después en `docs/QWEN3_NO_THINKING_GUIDE.md`. Baseline 2026-08-19:
  media 6,67 s con thinking ON.
- **Nota de formato (resuelta 2026-08-19)**: ambos modelos filtraban
  markdown (`**negrita**`, listas) al chat, que se renderiza en texto plano.
  El CEO agent ahora pasa sus respuestas por `_plain_chat_text` (quita
  negritas/cursivas/viñetas/encabezados/código) y el prompt pide explícitamente
  texto plano de chat; el bloque de datos de aprobaciones se resume por tipo
  con conteos (el LLM volcaba las 29 líneas técnicas). Verificado en vivo:
  «estado de los agentes» y «¿qué hay que aprobar?» responden en chat plano.
- **Opción de subida**: `qwen/qwen3.8-27b` ya está en LM Studio; es más
  lento pero con mejor calidad si el hardware lo permite (24 GB VRAM).

## Reproducción

```bash
# Qwen3 14B (LM Studio)
python .freebuff/bench_ceo_models.py --label qwen3-14b --out .freebuff/evidence_ceo_models_qwen3-14b.json
# deepseek-r1:8b (Ollama): cambiar .env.candidate-0815 (CHEAP/STANDARD_LLM_*=ollama/deepseek-r1:8b,
# OPENAI_BASE_URL/API_KEY vacías), recrear bridge-api, y repetir el benchmark.
python .freebuff/bench_ceo_models.py --label deepseek-r1-8b --out .freebuff/evidence_ceo_models_r1-8b.json
```
