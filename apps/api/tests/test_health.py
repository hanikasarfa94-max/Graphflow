from fastapi.testclient import TestClient

from workgraph_api.main import app

client = TestClient(app)


def test_health_returns_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["env"] == "dev"
    # Phase 7' fault-injection reads these counters to verify SSE/WS connections
    # drop to zero when clients disconnect. Presence + type is the contract.
    assert "sse_streams" in body
    assert "ws_streams" in body


def test_health_emits_trace_id_header():
    r = client.get("/health")
    assert r.headers.get("x-trace-id"), "trace_id header must be present"


def test_inbound_trace_id_is_echoed():
    r = client.get("/health", headers={"x-trace-id": "abc-123"})
    assert r.headers.get("x-trace-id") == "abc-123"
