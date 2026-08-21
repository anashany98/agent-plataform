SHELL := /bin/bash
CLIENT_ID ?= desarrollo-local
ENV_FILE ?= .env.$(CLIENT_ID)
PROJECT ?= agent-$(CLIENT_ID)
PROFILE ?= production
DOMAIN ?= $(CLIENT_ID).local
PROXY_PORT ?= 9000
TLS_CERTIFICATE ?=
TLS_PRIVATE_KEY ?=
PREFLIGHT_MODE ?= release
PREFLIGHT_FLAGS ?=
PYTHON ?= python3
COMPOSE_FILES = -f docker-compose.yml
ifeq ($(PROFILE),production)
COMPOSE_FILES += -f infrastructure/compose/docker-compose.prod.example.yml
endif
COMPOSE = docker compose --env-file $(ENV_FILE) -p $(PROJECT) $(COMPOSE_FILES) --profile $(PROFILE)
UP_BUILD_POLICY =
ifeq ($(PROFILE),production)
UP_BUILD_POLICY = --no-build --pull never
endif

.PHONY: check preflight verify-vendor-pins configure build release-manifest up down restart logs health smoke migrate-check test test-unit test-coverage typecheck lint backup restore clean-project status provision update rollback

preflight:
	@test -f "$(ENV_FILE)" || (echo "Falta $(ENV_FILE). Ejecuta make provision CLIENT_ID=$(CLIENT_ID)" >&2; exit 1)
	$(PYTHON) scripts/verify-compose-profiles.py
	$(PYTHON) scripts/verify-production-preflight.py
	$(PYTHON) scripts/verify-proxy-config.py
	$(PYTHON) scripts/verify-production-network.py
	$(PYTHON) scripts/verify-backup-format.py
	$(PYTHON) scripts/production-preflight.py --env-file "$(ENV_FILE)" --profile "$(PROFILE)" --mode "$(PREFLIGHT_MODE)" $(PREFLIGHT_FLAGS)

check: preflight verify-vendor-pins
	$(COMPOSE) config >/dev/null

# B-07: los forks de vendor/ (gitignored) deben coincidir con
# infrastructure/vendor-lock.json. En clones sin vendor/ (perfil core) el
# chequeo no aplica; con vendor/ presente, un pin divergente ROMPE el gate.
verify-vendor-pins:
	@if [ -d vendor ]; then $(PYTHON) scripts/verify-vendor-pins.py; else echo "vendor/ ausente (perfil core): verificación de pins no aplicable"; fi

provision:
	./scripts/provision-client.sh "$(CLIENT_ID)" "$(DOMAIN)" "$(PROXY_PORT)" "$(PROFILE)" "$(TLS_CERTIFICATE)" "$(TLS_PRIVATE_KEY)"

configure: provision

build:
	$(MAKE) preflight PREFLIGHT_MODE=bootstrap
	$(COMPOSE) build --pull

release-manifest:
	$(PYTHON) scripts/create-release-manifest.py --env-file "$(ENV_FILE)"

up: check
	$(COMPOSE) up -d $(UP_BUILD_POLICY) --wait --wait-timeout 600

status: check
	$(COMPOSE) ps

down: check
	$(COMPOSE) down --remove-orphans

restart: check
	$(COMPOSE) restart

logs: check
	$(COMPOSE) logs -f --tail=200

health: check
	@./scripts/check-health.sh "$(CLIENT_ID)" "$(PROFILE)"

smoke: health

migrate-check: check
	$(COMPOSE) run --rm --no-deps --entrypoint alembic bridge-api -c /app/alembic.ini check

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
	DEPLOY_PROFILE="$(PROFILE)" ./scripts/backup-restore-integral.sh backup "$(CLIENT_ID)"

restore:
	@test -n "$(ARCHIVE)" || (echo "Uso: make restore CLIENT_ID=x ARCHIVE=archivo.enc" >&2; exit 1)
	@test -n "$$BACKUP_ENCRYPTION_PASSPHRASE" || (echo "Define BACKUP_ENCRYPTION_PASSPHRASE" >&2; exit 1)
	DEPLOY_PROFILE="$(PROFILE)" ./scripts/backup-restore-integral.sh restore "$(CLIENT_ID)" "$(ARCHIVE)"

update:
	@test -n "$(TARGET_REF)" || (echo "Uso: make update CLIENT_ID=x TARGET_REF=v0.9.1" >&2; exit 1)
	./scripts/update-client.sh "$(CLIENT_ID)" "$(TARGET_REF)"

rollback:
	./scripts/rollback-client.sh "$(CLIENT_ID)"

clean-project: check
	@read -r -p "Esto eliminará contenedores y volúmenes de $(PROJECT). Escribe $(PROJECT): " answer; \
	[[ "$$answer" == "$(PROJECT)" ]] || { echo "Cancelado"; exit 1; }; \
	$(COMPOSE) down -v --remove-orphans
