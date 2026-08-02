# Operations Manual

## Monitoring & Logs
- View aggregated live container logs:
  ```bash
  make logs
  ```
- View specific service logs:
  ```bash
  docker logs -f bridge-api
  docker logs -f portal
  ```

## Restarting & Stopping Services
- Restart core services:
  ```bash
  make restart
  ```
- Stop services:
  ```bash
  make down
  ```

## Resource Health Verification
```bash
make health
```
