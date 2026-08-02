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
        'AUTO_SEED_DEMO_DATA': 'true',
        'CHATWOOT_WEBHOOK_SECRET': 'test-chatwoot-secret',
        'CHATWOOT_API_TOKEN': '',
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
    }
)

import pytest
from fastapi.testclient import TestClient

from app.main import app


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
