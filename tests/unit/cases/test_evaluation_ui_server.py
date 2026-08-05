"""Unit tests for Evaluation UI server."""

from fastapi.testclient import TestClient

from apps.evaluation_ui.main import app


def test_evaluation_ui_health_and_index():
    client = TestClient(app)

    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    res = client.get("/")
    assert res.status_code == 200
    assert "IDP" in res.text or "Claims" in res.text
