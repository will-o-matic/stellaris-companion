"""Tests for the dev/QA export endpoint POST /api/qa/export."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import backend.api.server as server


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _make_app(monkeypatch, companion=None):
    monkeypatch.setenv(server.ENV_API_TOKEN, "test-token")
    app = server.create_app()
    app.state.db = MagicMock()
    if companion is not None:
        app.state.companion = companion
    return app


def test_qa_export_requires_auth(monkeypatch):
    app = _make_app(monkeypatch)
    with TestClient(app) as client:
        resp = client.post("/api/qa/export", json={"output_path": "x.json"})
    assert resp.status_code == 401


def test_qa_export_503_when_no_save_loaded(monkeypatch):
    app = _make_app(monkeypatch)
    with TestClient(app) as client:
        resp = client.post(
            "/api/qa/export", headers=_auth_headers(), json={"output_path": "x.json"}
        )
    assert resp.status_code == 503


def test_qa_export_writes_file_and_returns_summary(monkeypatch, tmp_path):
    companion = MagicMock()
    companion.is_loaded = True
    companion.save_path = "dummy.sav"
    app = _make_app(monkeypatch, companion)

    fake_export = {
        "extraction": {"get_fleets": {}, "get_wars": {}},
        "audit": {"smell": [{"name": "fleets"}]},
    }
    monkeypatch.setattr(
        "stellaris_save_extractor.qa_export.run_full_export",
        lambda *a, **k: fake_export,
    )
    out = tmp_path / "export.json"

    with TestClient(app) as client:
        resp = client.post(
            "/api/qa/export", headers=_auth_headers(), json={"output_path": str(out)}
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["sections"] == 2
    assert data["smell_flags"] == 1
    assert data["path"] == str(out)
    assert out.exists()
