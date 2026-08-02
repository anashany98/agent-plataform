# Intento de build limpio

Comando solicitado:

```text
docker compose --profile full build --no-cache --pull --progress plain
```

Resultado: **BLOCKED**. Se canceló antes de terminar al medir:

```text
RAM host usada: 95,3 %
RAM libre: 1,49 GiB
```

Un arranque posterior con imágenes existentes elevó la RAM a 95,8 % y Chatwoot no alcanzó health. El stack `agent-platform-fixed` se dejó detenido; volúmenes intactos. No se detuvieron recursos ajenos.

