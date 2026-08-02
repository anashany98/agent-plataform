import asyncio
import datetime as dt
import io
import uuid

from app.database import SessionLocal
from app.main import _claim_idempotency
from app.models.models import IdempotencyRecord
from app.services.activepieces_adapter import ActivepiecesAdapter
from app.services.ghl_adapter import GHLAdapter
from app.services.prestashop_adapter import PrestaShopAdapter


def create_user(client, auth_headers, role='viewer', must_change=True):
    username = f'user-{uuid.uuid4().hex[:10]}'
    password = 'Temporary-Password-123!'
    response = client.post('/users', headers=auth_headers, json={
        'username': username, 'password': password, 'role': role, 'must_change_password': must_change,
    })
    assert response.status_code == 201, response.text
    return username, password


def test_temporary_password_is_enforced_and_change_revokes_token(client, auth_headers):
    username, password = create_user(client, auth_headers, role='viewer', must_change=True)
    login = client.post('/auth/login', json={'username': username, 'password': password})
    assert login.status_code == 200
    token = login.json()['access_token']
    assert login.json()['must_change_password'] is True
    headers = {'Authorization': f'Bearer {token}'}
    assert client.get('/tools/products?query=Industrial', headers=headers).status_code == 403
    changed = client.post('/auth/change-password', headers=headers, json={
        'current_password': password, 'new_password': 'New-Secure-Password-456!',
    })
    assert changed.status_code == 200, changed.text
    assert client.get('/tools/products?query=Industrial', headers=headers).status_code == 401
    new_login = client.post('/auth/login', json={'username': username, 'password': 'New-Secure-Password-456!'})
    assert new_login.status_code == 200
    assert new_login.json()['must_change_password'] is False


def test_logout_revokes_the_current_user_sessions(client, auth_headers):
    username, password = create_user(client, auth_headers, role='viewer', must_change=False)
    login = client.post('/auth/login', json={'username': username, 'password': password})
    headers = {'Authorization': f"Bearer {login.json()['access_token']}"}
    assert client.get('/tools/products?query=Industrial', headers=headers).status_code == 200
    assert client.post('/auth/logout', headers=headers).status_code == 200
    assert client.get('/tools/products?query=Industrial', headers=headers).status_code == 401


def test_viewer_cannot_approve_or_administer_users(client, auth_headers):
    username, password = create_user(client, auth_headers, role='viewer', must_change=False)
    token = client.post('/auth/login', json={'username': username, 'password': password}).json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    assert client.get('/users', headers=headers).status_code == 403
    assert client.post('/approvals/does-not-exist/approve', headers=headers, json={}).status_code == 403


def test_csv_upload_import_dry_run_is_validated(client, auth_headers):
    sku = f'CSV-{uuid.uuid4().hex[:12]}'
    csv_data = f'sku,name,base_price,tax_rate,stock_quantity\n{sku},Producto CSV,25.50,0.21,10\n'.encode()
    response = client.post(
        '/api/bridge/import-file/products?dry_run=true',
        headers=auth_headers,
        files={'file': ('productos.csv', io.BytesIO(csv_data), 'text/csv')},
    )
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'dry_run'
    assert response.json()['valid_rows'] == 1
    assert response.json()['invalid_rows'] == 0


def test_rag_role_acl_hides_document_from_viewer(client, auth_headers, tmp_path):
    username, password = create_user(client, auth_headers, role='viewer', must_change=False)
    viewer = client.post('/auth/login', json={'username': username, 'password': password}).json()['access_token']
    unique = f'claveultrasecreta{uuid.uuid4().hex}'
    document = tmp_path / 'solo-admin.txt'
    document.write_text(f'El código interno exclusivo es {unique}.', encoding='utf-8')
    ingest = client.post('/rag/ingest', headers=auth_headers, json={
        'doc_id': f'admin-{uuid.uuid4().hex[:12]}',
        'file_path': str(document),
        'metadata': {'allowed_roles': ['provider_admin']},
    })
    assert ingest.status_code == 200, ingest.text
    result = client.post('/rag/query', headers={'Authorization': f'Bearer {viewer}'}, json={'query': unique, 'min_score': 0.01})
    assert result.status_code == 200
    assert result.json()['abstained'] is True


def test_stale_processing_idempotency_claim_can_be_recovered():
    db = SessionLocal()
    key = f'stale-{uuid.uuid4().hex}'
    try:
        db.add(IdempotencyRecord(
            idempotency_key=key,
            response_body={'status': 'processing'},
            status_code=102,
            created_at=dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(minutes=10),
        ))
        db.commit()
        claimed, record = _claim_idempotency(db, key)
        assert claimed is True
        assert record is not None and record.status_code == 102
    finally:
        db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == key).delete()
        db.commit(); db.close()


def test_prestashop_contract_normalizes_localized_products(monkeypatch):
    adapter = PrestaShopAdapter()
    async def fake_get(resource, params):
        if resource == 'stock_availables': return {'stock_availables': [{'quantity': '7'}]}
        return {'products': [{'id': 42, 'reference': 'OF-42', 'name': {'language': [{'value': 'Silla Ergo'}]}, 'description_short': 'Ergonómica', 'price': '199.95', 'id_category_default': 3, 'active': 1}]}
    monkeypatch.setattr(adapter, '_get', fake_get)
    products = asyncio.run(adapter.search_products('silla'))
    assert products[0]['external_id'] == '42'
    assert products[0]['name'] == 'Silla Ergo'
    assert products[0]['stock_quantity'] == 7
    assert products[0]['base_price'] == 199.95


def test_ghl_contract_includes_location_and_external_reference(monkeypatch):
    adapter = GHLAdapter(); adapter.location_id = 'loc-1'
    calls = []
    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs)); return {'id': 'ok'}
    monkeypatch.setattr(adapter, '_request', fake_request)
    asyncio.run(adapter.upsert_contact(email='a@example.com', first_name='Ana'))
    monkeypatch.setattr('app.services.ghl_adapter.settings.GHL_PIPELINE_ID', 'pipe-1')
    monkeypatch.setattr('app.services.ghl_adapter.settings.GHL_PIPELINE_STAGE_ID', 'stage-1')
    asyncio.run(adapter.create_opportunity(contact_id='contact-1', name='Presupuesto', monetary_value=100, external_id='quote-1'))
    assert calls[0][2]['json']['locationId'] == 'loc-1'
    assert calls[1][2]['json']['customFields'][0]['field_value'] == 'quote-1'


def test_activepieces_contract_normalizes_webhook_path(monkeypatch):
    adapter = ActivepiecesAdapter(); captured = {}
    class Response:
        content = b'{"executionId":"exec-1"}'
        def raise_for_status(self): return None
        def json(self): return {'executionId': 'exec-1'}
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def post(self, url, **kwargs): captured['url'] = url; return Response()
    monkeypatch.setattr('app.services.activepieces_adapter.httpx.AsyncClient', lambda **kwargs: Client())
    result = asyncio.run(adapter.trigger_webhook('flow-test', {'x': 1}))
    assert captured['url'].endswith('/flow-test')
    assert result['executionId'] == 'exec-1'


def test_prestashop_enrichment_includes_features_combinations_and_specific_prices(monkeypatch):
    adapter = PrestaShopAdapter()

    async def fake_get(resource, params):
        if resource == 'products':
            return {
                'products': [{
                    'id': 42,
                    'reference': 'OF-42',
                    'name': {'language': [{'value': 'Silla Ergo'}]},
                    'description_short': '<p>Ergonómica y regulable</p>',
                    'price': '199.95',
                    'id_category_default': 3,
                    'active': 1,
                    'available_for_order': 1,
                    'show_price': 1,
                    'associations': {
                        'product_features': [{'id': 10, 'id_feature_value': 100}],
                        'combinations': [{'id': 900}],
                    },
                }]
            }
        if resource == 'stock_availables':
            combination = params.get('filter[id_product_attribute]')
            return {'stock_availables': [{'quantity': '3' if combination else '7'}]}
        if resource == 'product_features':
            return {'product_features': [{'id': 10, 'name': {'language': [{'value': 'Material'}]}}]}
        if resource == 'product_feature_values':
            return {'product_feature_values': [{'id': 100, 'id_feature': 10, 'custom': 0, 'value': {'language': [{'value': 'Malla'}]}}]}
        if resource == 'combinations':
            return {'combinations': [{
                'id': 900,
                'id_product': 42,
                'reference': 'OF-42-NEGRA',
                'price': '10.00',
                'default_on': 1,
                'minimal_quantity': 1,
                'associations': {'product_option_values': [{'id': 501}]},
            }]}
        if resource == 'product_option_values':
            return {'product_option_values': [{'id': 501, 'id_attribute_group': 50, 'name': {'language': [{'value': 'Negro'}]}}]}
        if resource == 'product_options':
            return {'product_options': [{'id': 50, 'name': {'language': [{'value': 'Color'}]}}]}
        if resource == 'specific_prices':
            return {'specific_prices': [{
                'id': 700,
                'id_product_attribute': 0,
                'id_shop': 1,
                'id_currency': 0,
                'id_country': 0,
                'id_group': 0,
                'id_customer': 0,
                'price': '-1',
                'from_quantity': 1,
                'reduction': '0.10',
                'reduction_tax': 1,
                'reduction_type': 'percentage',
            }]}
        if resource == 'categories':
            return {'categories': [{'id': 3, 'name': {'language': [{'value': 'Sillas de oficina'}]}}]}
        raise AssertionError(f'Recurso inesperado: {resource}')

    monkeypatch.setattr(adapter, '_get', fake_get)
    products = asyncio.run(adapter.search_products('silla', include_details=True))
    product = products[0]
    assert product['description'] == 'Ergonómica y regulable'
    assert product['category'] == 'Sillas de oficina'
    assert product['attributes']['features'][0]['name'] == 'Material'
    assert product['attributes']['features'][0]['value'] == 'Malla'
    combination = product['attributes']['combinations'][0]
    assert combination['reference'] == 'OF-42-NEGRA'
    assert combination['stock_quantity'] == 3
    assert combination['options'][0] == {
        'id': '501', 'group_id': '50', 'group': 'Color', 'value': 'Negro'
    }
    assert product['attributes']['specific_prices'][0]['reduction'] == 0.10


def test_product_search_matches_verified_features_not_only_exact_name(client, auth_headers):
    response = client.post('/api/bridge/import/products', headers=auth_headers, json={
        'dry_run': False,
        'items': [{
            'sku': f'ERG-{uuid.uuid4().hex[:8]}',
            'name': 'Asiento profesional',
            'description': 'Diseñado para jornadas largas',
            'category': 'Mobiliario',
            'base_price': 250,
            'tax_rate': 0.21,
            'stock_quantity': 4,
            'attributes': {'caracteristicas': ['soporte lumbar', 'reposabrazos regulables']},
        }],
    })
    assert response.status_code == 200, response.text
    found = client.get('/tools/products?query=necesito soporte lumbar para trabajar', headers=auth_headers)
    assert found.status_code == 200
    assert any('Asiento profesional' == row['name'] for row in found.json())
