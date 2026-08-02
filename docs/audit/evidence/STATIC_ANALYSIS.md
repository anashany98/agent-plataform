# Evidencia de análisis estático

| Herramienta | Resultado |
|---|---|
| Ruff | exit 1; 297 findings; 179 fixables |
| Black check | exit 1; 21 archivos se reformatearían |
| MyPy | exit 1; 71 errores/5 archivos |
| Bandit | exit 1; 0 high, 0 medium, 2 low |
| TypeScript | exit 0 |
| Prettier | exit 1; 5 archivos |
| ESLint | exit 2; falta `eslint.config.*` |
| Portal build | exit 0; Vite 5.4.21 |

Ruff por regla: UP006 120, B008 90, UP007 34, UP035 21, F401 9, I001 7, E702 5, B905 4, E402 3, UP017 2, E701 1, F811 1.

MyPy por archivo: `main.py` 51, `rag_service.py` 12, `deterministic_tools.py` 6, models 1, import 1.

