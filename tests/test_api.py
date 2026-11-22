"""Tests for engine/api.py: the localhost-only guards and /health (TestClient, mock mode, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import api
from engine.settings import Settings

MOCK = Settings(run_mode="mock")
LOCAL = "http://127.0.0.1:8000"
DASHBOARD = "http://localhost:3000"


@pytest.fixture
def app(tmp_path: Path):  # type: ignore[no-untyped-def]
    app = api.create_app(MOCK, db_path=tmp_path / "test.db", answers_path=tmp_path / "answers.json")

    @app.post("/_probe")  # a stand-in "changing" endpoint, only to test the guards
    def probe() -> dict[str, bool]:
        return {"changed": True}

    return app


@pytest.fixture
def client(app) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(app, base_url=LOCAL)


# ---- binding: the server refuses non-local hosts ----------------------------------------------


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "192.168.1.20", "example.com", "127.0.0.1.evil.com"])
def test_serve_refuses_non_local_hosts(host: str, monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []
    monkeypatch.setattr(api.uvicorn, "run", lambda *a, **k: started.append("started"))
    with pytest.raises(api.NotLocalError, match="127.0.0.1"):
        api.serve(host)
    assert started == []  # the server never even started


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_serve_accepts_local_hosts_and_passes_the_same_host_on(host: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(api.uvicorn, "run", lambda app, **kw: seen.update(kw))
    api.serve(host, 8123)
    assert seen["host"] == host and seen["port"] == 8123


def test_main_refuses_with_exit_code_1(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    # uvicorn.run is faked in EVERY server test, so a broken guard fails the test instead of opening a real port.
    monkeypatch.setattr(api.uvicorn, "run", lambda *a, **k: None)
    assert api.main(["--host", "0.0.0.0"]) == 1
    assert "Refusing" in capsys.readouterr().out


# ---- Host check -------------------------------------------------------------------------------


def test_health_reports_ok_and_the_mode(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "run_mode": "mock"}


@pytest.mark.parametrize("base", ["http://evil.example", "http://192.168.1.20:8000", "http://127.0.0.1.evil.com:8000"])
def test_wrong_host_header_is_refused(app, base: str) -> None:  # type: ignore[no-untyped-def]
    assert TestClient(app, base_url=base).get("/health").status_code == 403


@pytest.mark.parametrize("base", ["http://localhost:8000", "http://127.0.0.1:9999", "http://[::1]:8000"])
def test_local_host_names_are_accepted(app, base: str) -> None:  # type: ignore[no-untyped-def]
    assert TestClient(app, base_url=base).get("/health").status_code == 200


# ---- Origin check -----------------------------------------------------------------------------


def test_change_from_another_website_is_refused(client: TestClient) -> None:
    response = client.post("/_probe", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_change_from_origin_null_is_refused(client: TestClient) -> None:
    assert client.post("/_probe", headers={"Origin": "null"}).status_code == 403


@pytest.mark.parametrize("origin", [DASHBOARD, "http://127.0.0.1:3000"])
def test_change_from_the_dashboard_is_allowed(client: TestClient, origin: str) -> None:
    assert client.post("/_probe", headers={"Origin": origin}).json() == {"changed": True}


def test_change_with_no_origin_is_allowed(client: TestClient) -> None:
    """PowerShell, curl and scripts send no Origin: they are not web pages."""
    assert client.post("/_probe").status_code == 200


def test_reading_from_another_origin_is_not_blocked_by_the_origin_check_but_cors_hides_it(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers  # the browser will not show the page the answer


# ---- CORS -------------------------------------------------------------------------------------


def preflight(client: TestClient, origin: str, method: str = "POST"):  # type: ignore[no-untyped-def]
    return client.options(
        "/_probe", headers={"Origin": origin, "Access-Control-Request-Method": method, "Access-Control-Request-Headers": "content-type"}
    )


def test_cors_allows_the_dashboard_only(client: TestClient) -> None:
    assert preflight(client, DASHBOARD).headers.get("access-control-allow-origin") == DASHBOARD
    assert "access-control-allow-origin" not in preflight(client, "https://evil.example").headers


# ---- misc -------------------------------------------------------------------------------------


def test_new_database_gets_its_tables(tmp_path: Path) -> None:
    from engine import db

    path = tmp_path / "fresh.db"
    api.create_app(MOCK, db_path=path)
    conn = db.connect(path)
    assert "fills" in db.table_names(conn)
    conn.close()


def test_request_connection_works_across_threads(app, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """A sync dependency may open and close on different worker threads; the connection must allow it."""
    from fastapi import Depends

    @app.get("/_count")
    def count(conn=Depends(api.get_conn)) -> dict[str, int]:  # type: ignore[no-untyped-def]
        return {"fills": conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0]}

    assert TestClient(app, base_url=LOCAL).get("/_count").json() == {"fills": 0}


def test_api_source_has_no_button_clicks_and_no_mode_changes() -> None:
    """The API never submits and never edits settings.json (the mode is yours to change)."""
    source = Path(api.__file__).read_text(encoding="utf-8")
    for forbidden in (".click(", "settings.json", "write_text"):
        assert forbidden not in source.replace("``settings.json``", ""), forbidden
