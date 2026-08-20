from fastapi.testclient import TestClient

from engine.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_trigger_mf_job(monkeypatch):
    def mock_run_mf_background_job(*args, **kwargs):
        pass

    import engine.main

    monkeypatch.setattr(
        engine.main, "run_mf_background_job", mock_run_mf_background_job
    )

    payload = {"job_type": "refresh_nav", "force_refresh": False, "scheme_codes": []}
    response = client.post("/mf/trigger-job", json=payload)
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
