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


# ---- read endpoints (stage 4.4c) --------------------------------------------------------------

SALARY = "What is your expected monthly salary?"
CRIME = "Have you ever been convicted of a crime?"
PHONE = "+63 917 555 0199"


@pytest.fixture
def seeded(tmp_path: Path):  # type: ignore[no-untyped-def]
    """An app whose temporary database holds a little of everything, plus a connection to add more."""
    import json

    from engine import db, learning
    from engine.profile import load_answers

    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            [
                {"question": SALARY, "answer": "PHP 20,000", "location_scope": "city", "city": "Makati", "kind": "fixed", "also_asked_as": ["Expected salary"]},
                {"question": SALARY, "answer": "USD 600", "location_scope": "remote", "kind": "fixed"},
                {"question": CRIME, "answer": "No", "kind": "protected"},
                {"question": "Anything else?", "answer": "No", "kind": "open"},
            ]
        ),
        encoding="utf-8",
    )
    path = tmp_path / "test.db"
    app = api.create_app(MOCK, db_path=path, answers_path=answers)
    conn = db.connect(path)
    load_answers(conn, answers)
    yield TestClient(app, base_url=LOCAL), conn, learning
    conn.close()


def test_empty_lists_are_empty_not_errors(client: TestClient) -> None:
    for url in ("/unknown", "/wordings", "/answers", "/fills"):
        response = client.get(url)
        assert response.status_code == 200 and response.json() == [], url


def test_unknown_lists_most_seen_first_with_options(seeded) -> None:  # type: ignore[no-untyped-def]
    client, conn, learning = seeded
    learning.record_unknown(conn, "Favourite colour?", "https://x.test/1", "text")
    learning.record_unknown(conn, "Preferred shift?", "https://x.test/2", "select", ("Day", "Night"))
    learning.record_unknown(conn, "Preferred shift?", "https://x.test/3", "select", ("Day", "Night"))
    rows = client.get("/unknown").json()
    assert [r["question"] for r in rows] == ["Preferred shift?", "Favourite colour?"]
    assert rows[0]["times_seen"] == 2 and rows[0]["options"] == ["Day", "Night"] and rows[0]["field_type"] == "select"
    conn.execute("UPDATE unknown_questions SET status = 'answered' WHERE id = ?", (rows[1]["id"],))
    conn.commit()
    assert [r["question"] for r in client.get("/unknown").json()] == ["Preferred shift?"]  # answered ones leave


def test_wordings_carry_protected_flag_and_kind(seeded) -> None:  # type: ignore[no-untyped-def]
    client, conn, learning = seeded
    learning.suggest_wording(conn, "How much pay do you want?", SALARY, 0.88, "https://x.test/a")
    learning.suggest_wording(conn, "Any criminal record?", CRIME, 0.91, "https://x.test/b")
    learning.suggest_wording(conn, "Any criminal record?", CRIME, 0.91, "https://x.test/c")
    rows = client.get("/wordings").json()
    assert [r["wording"] for r in rows] == ["Any criminal record?", "How much pay do you want?"]  # most seen first
    assert rows[0]["protected"] is True and rows[0]["kind"] == "protected" and rows[0]["times_seen"] == 2
    assert rows[1]["protected"] is False and rows[1]["kind"] == "fixed" and rows[1]["score"] == 0.88
    learning.reject_wording(conn, rows[1]["id"])
    assert [r["wording"] for r in client.get("/wordings").json()] == ["Any criminal record?"]  # decided ones leave


def test_answers_include_text_kind_scope_and_wordings(seeded) -> None:  # type: ignore[no-untyped-def]
    client, _conn, _learning = seeded
    rows = client.get("/answers").json()
    assert [(r["question"], r["location_scope"]) for r in rows] == [
        ("Anything else?", "any"), (CRIME, "any"), (SALARY, "city"), (SALARY, "remote"),
    ]
    by_scope = {r["location_scope"]: r for r in rows if r["question"] == SALARY}
    assert by_scope["city"]["answer"] == "PHP 20,000" and by_scope["city"]["city"] == "Makati"
    assert by_scope["city"]["also_asked_as"] == by_scope["remote"]["also_asked_as"] == ["Expected salary"]  # shared by variants
    assert next(r for r in rows if r["question"] == CRIME)["kind"] == "protected"


def _save(conn, report, **kw) -> int:  # type: ignore[no-untyped-def]
    from engine.forms.history import save_fill

    return save_fill(conn, report, **kw)


def _report(url: str, *results):  # type: ignore[no-untyped-def]
    from engine.forms.filler import FieldResult, FillReport

    return FillReport(url=url, results=[FieldResult(*r) if not isinstance(r, FieldResult) else r for r in results])


def test_fills_newest_first_filter_and_limit(seeded) -> None:  # type: ignore[no-untyped-def]
    from engine.forms.history import mark_fill

    client, conn, _ = seeded
    for n in (1, 2, 3):
        _save(conn, _report(f"https://jobs.test/{n}", ("Full name", "text", "filled")), job_title=f"Job {n}", resume_id=None)
    mark_fill(conn, 1, "submitted")
    assert [r["url"] for r in client.get("/fills").json()] == ["https://jobs.test/3", "https://jobs.test/2", "https://jobs.test/1"]
    assert [r["job_title"] for r in client.get("/fills?status=filled").json()] == ["Job 3", "Job 2"]
    assert [r["status"] for r in client.get("/fills?status=submitted").json()] == ["submitted"]
    assert len(client.get("/fills?limit=1").json()) == 1


@pytest.mark.parametrize("query", ["status=bogus", "limit=0", "limit=501", "limit=abc"])
def test_fills_rejects_bad_query(client: TestClient, query: str) -> None:
    assert client.get(f"/fills?{query}").status_code == 422


def test_fills_never_return_typed_values(seeded) -> None:  # type: ignore[no-untyped-def]
    from engine.forms.filler import FieldResult

    client, conn, _ = seeded
    conn.execute(
        "INSERT INTO profile (id, full_name, email, phone, address) VALUES (1, ?, ?, ?, ?)",
        ("Test Person", "tp@example.test", PHONE, "Somewhere"),
    )
    conn.commit()
    report = _report(
        "https://jobs.test/x",
        FieldResult("Mobile number", "text", "filled"),
        FieldResult("Why us?", "textarea", "filled", note=f"guess; call {PHONE}", flagged=True),
    )
    _save(conn, report, job_title="Analyst", resume_id=None)
    response = client.get("/fills")
    row = response.json()[0]
    assert row["filled_fields"] == ["Mobile number", "Why us?"] and row["filled_count"] == 2
    assert row["flagged_fields"][0]["label"] == "Why us?"
    assert PHONE not in response.text and "tp@example.test" not in response.text  # scrubbed before saving, never returned
    from engine.api_models import FillOut

    assert set(row) == set(FillOut.model_fields)  # nothing outside the contract


@pytest.mark.parametrize("url", ["/unknown", "/wordings", "/answers", "/fills"])
def test_read_endpoints_refuse_a_foreign_host(seeded, url: str) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = seeded
    foreign = TestClient(client.app, base_url="http://evil.example")
    assert foreign.get(url).status_code == 403


def test_read_endpoints_change_nothing(seeded) -> None:  # type: ignore[no-untyped-def]
    client, conn, learning = seeded
    learning.record_unknown(conn, "Q?", "", "text")
    learning.suggest_wording(conn, "Pay?", SALARY, 0.9)

    def snapshot() -> list[tuple]:
        return [tuple(r) for t in ("unknown_questions", "suggested_wordings") for r in conn.execute(f"SELECT * FROM {t}")]

    before = snapshot()
    for url in ("/unknown", "/wordings", "/answers", "/fills"):
        client.get(url)
    assert snapshot() == before  # a look never raises times_seen
