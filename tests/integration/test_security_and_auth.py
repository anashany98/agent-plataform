import hashlib
import hmac
import json
import time
import uuid


def signed_request(client, payload: dict, *, timestamp: int | None = None, secret: str = 'test-chatwoot-secret'):
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    ts = str(timestamp or int(time.time()))
    signature = hmac.new(secret.encode(), ts.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return client.post(
        '/webhooks/chatwoot',
        content=raw,
        headers={'Content-Type': 'application/json', 'X-Chatwoot-Timestamp': ts, 'X-Chatwoot-Signature': f'sha256={signature}'},
    )


def test_sensitive_endpoints_require_authentication(client):
    assert client.get('/approvals').status_code == 401
    assert client.get('/costs').status_code == 401
    assert client.post('/agents/run', json={'prompt': 'hola'}).status_code == 401
    assert client.post('/api/bridge/import/products', json={'items': [{'sku': 'X', 'name': 'X', 'base_price': 1}]}).status_code == 401


def test_login_rejects_bad_password(client):
    response = client.post('/auth/login', json={'username': 'admin', 'password': 'bad'})
    assert response.status_code == 401


def test_unsigned_and_invalid_webhooks_are_rejected(client):
    payload = {'event': 'message_created', 'id': str(uuid.uuid4()), 'message_type': 'incoming', 'content': 'Hola', 'conversation': {'id': 1}, 'account': {'id': 1}}
    assert client.post('/webhooks/chatwoot', json=payload).status_code == 401
    assert signed_request(client, payload, secret='wrong-secret').status_code == 401
    assert signed_request(client, payload, timestamp=int(time.time()) - 1000).status_code == 401


def test_signed_webhook_and_message_id_idempotency(client):
    payload = {'event': 'message_created', 'id': f'msg-{uuid.uuid4().hex}', 'message_type': 'incoming', 'content': 'Hola', 'conversation': {'id': 5}, 'account': {'id': 1}}
    first = signed_request(client, payload)
    assert first.status_code == 200, first.text
    assert first.json()['status'] == 'success'
    second = signed_request(client, payload)
    assert second.status_code == 200
    assert second.json()['status'] == 'duplicate_ignored'


def test_openapi_declares_bearer_security(client):
    schema = client.get('/openapi.json').json()
    schemes = schema['components']['securitySchemes']
    assert any(item.get('type') == 'http' for item in schemes.values())
