"""Unit tests for Field Transformation & Escalation Visualizer UI server."""

from fastapi.testclient import TestClient

from apps.transformation_ui.main import app


def test_transformation_ui_health_and_index():
    client = TestClient(app)

    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    res = client.get("/")
    assert res.status_code == 200
    assert "Field Transformation" in res.text

    res = client.get("/styles.css")
    assert res.status_code == 200
    assert "main-grid" in res.text

    res = client.get("/app.js")
    assert res.status_code == 200
    assert "DOCUMENTS" in res.text
