import os
from pathlib import Path

TEST_DB = Path('/tmp/agent_platform_fixed_tests.db')
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ.update(
    {
        'DATABASE_URL': f'sqlite:///{TEST_DB}',
        'ENVIRONMENT': 'testing',
        'INSTALLATION_ID': 'test-installation',
        'AUTH_SECRET': 'test-auth-secret-at-least-32-characters-long',
        'INITIAL_ADMIN_USERNAME': 'admin',
        'INITIAL_ADMIN_PASSWORD': 'Test-Password-123!',
        'AUTO_CREATE_SCHEMA': 'true',
        'ALLOW_DEMO_DATA': 'false',
        'AUTO_SEED_DEMO_DATA': 'false',
        'CHATWOOT_WEBHOOK_SECRET': 'test-chatwoot-secret',
        'CHATWOOT_API_TOKEN': '',
        'CHATWOOT_HANDOFF_TEAM_ID': '1',
        'ALLOW_INTEGRATION_STUBS': 'true',
        'ALLOW_MOCK_LLM': 'true',
        'STANDARD_LLM_PROVIDER': 'mock',
        'STANDARD_LLM_MODEL': 'test-model',
        'CHEAP_LLM_PROVIDER': 'mock',
        'CHEAP_LLM_MODEL': 'test-model-cheap',
        'EMBEDDING_PROVIDER': 'local_tfidf',
        'EMBEDDING_DIMENSION': '384',
        'RAG_ALLOWED_ROOTS': '/tmp',
        'RAG_UPLOAD_DIR': '/tmp/agent-platform-uploads',
        'RATE_LIMIT_ENABLED': 'false',
        'RAG_MIN_SCORE': '0.05',
        'ALLOWED_ORIGINS': 'http://testserver',
        'ALLOWED_HOSTS': 'testserver,localhost,127.0.0.1',
        'CIRCUIT_BREAKER_FAILURE_THRESHOLD': '3',
        'CIRCUIT_BREAKER_RECOVERY_SEC': '1',
        'OUTBOX_MAX_ATTEMPTS': '3',
        'OUTBOX_RETRY_BASE_DELAY_SEC': '0.01',
        'OUTBOX_RETRY_MAX_DELAY_SEC': '0.05',
        'OUTBOX_BATCH_SIZE': '8',
    }
)

# Los imports van después de fijar las variables de entorno: el harness
# hermético (D-032) exige que los tests no dependan del entorno del operador.
import pytest  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import Customer, Pricelist, Product  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_circuit_breakers():
    """Cada test parte de circuitos cerrados: el estado global no se hereda."""

    from app.services.resilience import reset_all_breakers

    reset_all_breakers()
    yield
    reset_all_breakers()


@pytest.fixture(scope='session', autouse=True)
def synthetic_business_fixtures() -> None:
    """Provide explicit non-demo fixtures for the historical integration suite."""
    from decimal import Decimal

    db = SessionLocal()
    try:
        pricelist = db.query(Pricelist).filter(Pricelist.id == 'pl-distributor').first()
        if not pricelist:
            db.add(Pricelist(id='pl-distributor', name='Distribuidor de prueba', discount_percentage=Decimal('20')))
        if not db.query(Customer).filter(Customer.id == 'cust-004').first():
            db.add(
                Customer(
                    id='cust-004',
                    name='Cliente sintético 004',
                    email='customer-004@example.invalid',
                    pricelist_id='pl-distributor',
                )
            )
        for index in (1, 6):
            sku = f'SKU-IND-{index:04d}'
            if db.query(Product).filter(Product.sku == sku).first():
                continue
            db.add(
                Product(
                    id=f'fixture-industrial-{index}',
                    external_id=f'fixture-industrial-{index}',
                    sku=sku,
                    name=f'Producto Industrial Modelo {index}',
                    description='Fixture local sintético, no demo, para pruebas de comercio.',
                    category='Industrial',
                    attributes={'fixture': True},
                    source='local',
                    base_price=Decimal('100.00') + index,
                    tax_rate=Decimal('0.21'),
                    stock_quantity=100,
                    reserved_stock=0,
                )
            )
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope='session')
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope='session')
def token(client: TestClient) -> str:
    response = client.post('/auth/login', json={'username': 'admin', 'password': 'Test-Password-123!'})
    assert response.status_code == 200, response.text
    return response.json()['access_token']


@pytest.fixture
def auth_headers(token: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}
