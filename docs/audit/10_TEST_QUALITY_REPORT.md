> **SUPERSEDED — NO UTILIZAR PARA DECISIONES ACTUALES.** Evidencia histórica de una fase/commit anterior. Se conserva para trazabilidad; el estado vigente está en `docs/PRODUCTION_READINESS.md` y los informes de 2026-08-15.

# 10 - Calidad de tests

## Ejecución reproducida

`31 passed, 2 warnings in 4.96s`, Python 3.12.13, Linux, cobertura total 67 % (2.361 statements, 783 sin cubrir). Código y tests se montaron read-only; coverage se escribió en `/tmp`. Resultado reproducible con la imagen Bridge existente y dependencias dev.

## Entorno de test y límite de validez

Todos los tests usan SQLite, `AUTO_SEED_DEMO_DATA=true`, `ALLOW_INTEGRATION_STUBS=true`, `ALLOW_MOCK_LLM=true`, modelo mock, embedding `local_tfidf`, rate limit deshabilitado y orígenes ficticios. Por tanto, **ningún test verifica PrestaShop, GHL, Chatwoot, Activepieces, Ollama, PostgreSQL/pgvector o proxy reales**.

## Inventario por test

Leyenda: `M` usa mock/stub/demo; `E` comprueba efecto persistente; `FP` tiene riesgo claro de falso positivo respecto al producto real. Todos obtuvieron PASS.

| Test | Componente/tipo | Qué comprueba | M/E/FP | Resultado y observación |
|---|---|---|---|---|
| `test_health_and_ready` | Health/integración local | DB SQLite sana | M, FP | PASS; no prueba health degradado ni Docker |
| `test_authenticated_read_endpoints` | API/auth | Productos y dashboard | M, FP | PASS sobre demo |
| `test_sensitive_endpoints_require_authentication` | Seguridad | 401 sin bearer | — | PASS; efecto adecuado |
| `test_login_rejects_bad_password` | Auth | Password inválida | — | PASS |
| `test_unsigned_and_invalid_webhooks_are_rejected` | HMAC | Firma/timestamp | M | PASS; payload sintético |
| `test_signed_webhook_and_message_id_idempotency` | Webhook | Dedup secuencial | M, E, FP | PASS; Chatwoot response stub |
| `test_openapi_declares_bearer_security` | OpenAPI | Scheme HTTP | —, FP | PASS; no revisa seguridad por ruta |
| `test_customer_pricelist_discount_is_applied` | Pricing/unit | Descuento local | M, E, FP | PASS; no precio PrestaShop |
| `test_conversation_can_only_confirm_its_own_quote` | Comercio | Scoping por conversación | M, E | PASS SQLite |
| `test_repeated_confirmation_is_business_idempotent` | Comercio | Una orden por quote | M, E, FP | PASS secuencial, no concurrente |
| `test_insufficient_stock_rolls_back_entire_order` | Comercio | Rollback local | M, E, FP | PASS; manipula demo |
| `test_approval_is_single_use_and_reviewer_comes_from_token` | Aprobación | Reuso secuencial | M, E, FP | PASS; no race |
| `test_atomic_stock_reservation_rejects_overbooking` | Stock | Update condicional | M, E | PASS una sesión |
| `test_generic_recommendation_uses_only_verified_catalog_data` | Recomendación | Producto importado en respuesta | M, E, FP | PASS, pero no afirma que se excluya `source=demo` |
| `test_temporary_password_is_enforced_and_change_revokes_token` | Auth | Cambio/revocación | M, E | PASS |
| `test_logout_revokes_the_current_user_sessions` | Auth | Versionado token | M, E | PASS |
| `test_viewer_cannot_approve_or_administer_users` | RBAC | 403 viewer | M | PASS |
| `test_csv_upload_import_dry_run_is_validated` | Import | Parse/dry-run | M | PASS; no commit/volumen |
| `test_rag_role_acl_hides_document_from_viewer` | RAG ACL | Rol de documento | M, E | PASS TF-IDF local |
| `test_stale_processing_idempotency_claim_can_be_recovered` | Idempotencia | Reclamo stale | M, E, FP | PASS; sin concurrencia |
| `test_prestashop_contract_normalizes_localized_products` | Contrato | Normalización | M, FP | PASS con `fake_get` |
| `test_ghl_contract_includes_location_and_external_reference` | Contrato | Payload GHL | M, FP | PASS con request falso |
| `test_activepieces_contract_normalizes_webhook_path` | Contrato | URL/ID | M, FP | PASS con cliente falso |
| `test_prestashop_enrichment_includes_features_combinations_and_specific_prices` | Contrato | Enriquecimiento | M, FP | PASS; no uso en pricing |
| `test_product_search_matches_verified_features_not_only_exact_name` | Búsqueda | Atributos importados | M, E, FP | PASS; “verified” sin modelo de procedencia |
| `test_missing_rag_file_is_rejected` | RAG | Ruta inexistente | M, E | PASS |
| `test_rag_persists_real_file_and_citations` | RAG | TXT/chunks/citas | M, E, FP | PASS; embedding TF-IDF, no pgvector real |
| `test_rag_refuses_secret_exfiltration` | RAG seguridad | Palabras bloqueadas | M, FP | PASS; bypass por paráfrasis no probado |
| `test_llm_mock_is_explicit_not_disguised_as_openai` | LLM | Mock marcado | M | PASS; confirma que no es real |
| `test_prestashop_and_ghl_fail_closed_without_credentials` | Integraciones | Error sin credencial | M | PASS; no éxito real |
| `test_importer_detects_duplicates_and_missing_stock_product` | Import | Validaciones | M, E | PASS |

## Cobertura por áreas críticas

- `main.py`: 62 %; sin cubrir gran parte de GHL, PrestaShop sync, Activepieces, uploads y ramas de error.
- RAG: 45 %; LLM router: 50 %; importador: 51 %; rate limit: 44 %.
- Chatwoot adapter: 64 %. Servicio determinista: 73 %.
- Frontend: sin tests/cobertura.

## Falsos positivos relevantes

1. El test “solo catálogo verificado” prueba presencia de un import, no ausencia de demo.
2. Idempotencia/aprobación son secuenciales y no detectan races.
3. Los contratos de terceros verifican la implementación contra el propio fake.
4. Health solo prueba el camino sano y acepta el diseño HTTP 200.
5. La suite no contiene `no acepto`, precios específicos aplicados, variante elegida, frescura o pedido PrestaShop.

## Archivos revisados, riesgos y pendiente

Se revisaron `conftest.py` y los cinco módulos de tests completos. La suite es útil como regresión local, pero no justifica un piloto. Debe separarse en unit, PostgreSQL integration, contract sandbox y e2e, y eliminar lenguaje “verified” donde no existe procedencia.
