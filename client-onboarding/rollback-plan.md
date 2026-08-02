# Plan de Rollback y Desconexión de Emergencia

**Objetivo:** Procedimiento seguro de desconexión del piloto o reversión a un estado anterior.

---

## 1. Desconexión Rápida del Widget de Chat
En caso de necesidad de pausa inmediata de la atención automatizada:
1. Retirar el script del widget de Chatwoot de la web del cliente.
2. O bien activar el **Kill Switch** en el Admin Portal en `Agentes de IA` -> `Desactivar Agente`.

## 2. Restauración de Copia de Seguridad Anterior
Ejecutar desde el servidor host:
```powershell
pwsh -File ./scripts/rollback-client.ps1 -ClientId "cliente-piloto" -BackupPath "./backups/pre_update_..."
```
