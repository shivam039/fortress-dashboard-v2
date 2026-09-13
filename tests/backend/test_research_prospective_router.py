from fastapi.testclient import TestClient

from main import app


def test_prospective_status_is_read_only_and_reports_milestone(monkeypatch):
    monkeypatch.setattr(
        "research.prospective_store.get_status",
        lambda: {"total_observations": 12, "matured_outcomes": 3},
    )

    response = TestClient(app).get("/api/research/prospective/status")

    assert response.status_code == 200
    assert response.json() == {"total_observations": 12, "matured_outcomes": 3}
