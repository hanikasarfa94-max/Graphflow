from fastapi import FastAPI
from fastapi.testclient import TestClient

from workgraph_api.main import app
from workgraph_schemas import ApiError


def test_unhandled_exception_becomes_api_error():
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/_debug/boom")
    assert r.status_code == 500
    body = r.json()
    ApiError.model_validate(body)
    assert body["code"] == "internal_error"
    assert body["message"] == "internal server error"
    assert body["details"]["type"] == "RuntimeError"
    assert body["trace_id"], "trace_id must be attached"


def test_404_uses_api_error_shape():
    client = TestClient(app)
    r = client.get("/does-not-exist")
    assert r.status_code == 404
    ApiError.model_validate(r.json())
    assert r.json()["code"] == "not_found"


def test_env_loader_raises_on_invalid(monkeypatch):
    # Force an invalid value for a Literal-typed field and ensure we fail fast.
    monkeypatch.setenv("WORKGRAPH_ENV", "nonsense")
    from workgraph_api.settings import load_settings

    try:
        load_settings()
    except RuntimeError as exc:
        assert "WORKGRAPH_" in str(exc)
    else:
        raise AssertionError("expected RuntimeError from invalid env")
