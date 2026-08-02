def test_health_and_ready(client):
    health = client.get('/health')
    assert health.status_code == 200
    assert health.json()['db_status'] == 'healthy'
    assert client.get('/ready').json() == {'status': 'ready'}


def test_authenticated_read_endpoints(client, auth_headers):
    products = client.get('/tools/products?query=Industrial', headers=auth_headers)
    assert products.status_code == 200
    assert products.json()
    dashboard = client.get('/provider/dashboard', headers=auth_headers)
    assert dashboard.status_code == 200
    assert dashboard.json()['installation_id'] == 'test-installation'
