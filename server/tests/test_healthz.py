from app import create_app


def test_healthz_returns_ok():
    app = create_app({"TESTING": True})
    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
