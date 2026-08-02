SHELL := /bin/bash
CLIENT_ID ?= desarrollo-local
ENV_FILE ?= .env.$(CLIENT_ID)
PROJECT ?= agent-$(CLIENT_ID)
COMPOSE = docker compose --env-file $(ENV_FILE) -p $(PROJECT) --profile full

.PHONY: check configure build up down restart logs health test test-unit test-coverage typecheck lint backup restore clean-project status provision update rollback

check:
	@test -f "$(ENV_FILE)" || (echo "Falta $(ENV_FILE). Ejecuta make provision CLIENT_ID=$(CLIENT_ID)" >&2; exit 1)
	$(COMPOSE) config >/dev/null

provision:
	./scripts/provision-client.sh "$(CLIENT_ID)" "$(CLIENT_ID).local" "$${PROXY_PORT:-9000}"

configure: provision

build: check
	$(COMPOSE) build --pull

up: check
	$(COMPOSE) up -d

status: check
	$(COMPOSE) ps

down: check
	$(COMPOSE) down --remove-orphans

restart: check
	$(COMPOSE) restart

logs: check
	$(COMPOSE) logs -f --tail=200

health: check
	@./scripts/check-health.sh "$(CLIENT_ID)"

test: test-unit typecheck

test-unit:
	PYTHONPATH=bridge-api pytest -q tests

test-coverage:
	PYTHONPATH=bridge-api pytest --cov=bridge-api/app --cov-report=term-missing --cov-report=xml:coverage.xml tests

typecheck:
	cd portal && npm run typecheck

lint:
	python -m ruff check bridge-api/app tests
	cd portal && npm run format:check

backup: check
	@test -n "$$BACKUP_ENCRYPTION_PASSPHRASE" || (echo "Define BACKUP_ENCRYPTION_PASSPHRASE" >&2; exit 1)
	./scripts/backup-restore-integral.sh backup "$(CLIENT_ID)"

restore: check
	@test -n "$(ARCHIVE)" || (echo "Uso: make restore CLIENT_ID=x ARCHIVE=archivo.enc" >&2; exit 1)
	@test -n "$$BACKUP_ENCRYPTION_PASSPHRASE" || (echo "Define BACKUP_ENCRYPTION_PASSPHRASE" >&2; exit 1)
	./scripts/backup-restore-integral.sh restore "$(CLIENT_ID)" "$(ARCHIVE)"

update: check
	@test -n "$(TARGET_REF)" || (echo "Uso: make update CLIENT_ID=x TARGET_REF=v0.9.1" >&2; exit 1)
	./scripts/update-client.sh "$(CLIENT_ID)" "$(TARGET_REF)"

rollback: check
	./scripts/rollback-client.sh "$(CLIENT_ID)"

clean-project: check
	@read -r -p "Esto eliminará contenedores y volúmenes de $(PROJECT). Escribe $(PROJECT): " answer; \
	[[ "$$answer" == "$(PROJECT)" ]] || { echo "Cancelado"; exit 1; }; \
	$(COMPOSE) down -v --remove-orphans
