# Protocolo de Preparación de Datos y Privacidad del Cliente

**Fecha:** 2026-07-31  
**Garantía de Aislamiento:** Single-Tenant Client Isolated Stack  

---

## Criterios de Protección de Datos:
1. **Cifrado en Transición y Reposo:** Todas las conexiones HTTP se redirigen a HTTPS mediante certificados TLS. Las bases de datos PostgreSQL residen en redes privadas de Docker inaccesibles desde el exterior.
2. **Aislamiento Estricto:** Prohibida la copia de datos reales de clientes hacia entornos de desarrollo o repositorios de código.
3. **Política de Retención:** Los registros de auditoría y conversaciones se conservan durante el periodo acordado (30 días de piloto) con soporte para exportación completa en formato JSON/CSV y borrado definitivo a petición.
