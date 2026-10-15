"""Account isolation, CSRF, hosted file proof and anonymous-tool security checks."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from aiseoonline_api import accounts
from aiseoonline_api.config import Settings
from aiseoonline_api.db.base import Base
from aiseoonline_api.db.models import AuditJob, Project, UserSession
from aiseoonline_api.main import create_app

ORIGIN = {"Origin": "http://testserver"}
GOOD = "sufficiently-long-test-password"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_throttle", lambda *args, **kwargs: True)
    uri = "sqlite:///" + str(tmp_path / "private.sqlite")
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=uri,
        auth_registration_enabled=True,
    )
    app = create_app(settings)

    @event.listens_for(app.state.database_engine, "connect")
    def enforce_relations(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(app.state.database_engine)
    with TestClient(app, base_url="https://testserver") as client:
        yield client, app.state.database_engine


def _register(client, email):
    response = client.post(
        "/api/v1/account/register",
        headers=ORIGIN,
        json={"email": email, "password": GOOD},
    )
    assert response.status_code == 201, response.text


def _login(client, email):
    response = client.post(
        "/api/v1/account/login",
        headers=ORIGIN,
        json={"email": email, "password": GOOD},
    )
    assert response.status_code == 200, response.text
    assert response.cookies.get("__Host-aiseo_session")
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    return {**ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def test_account_sessions_are_revocable_and_hidden(api):
    client, db = api
    _register(client, "sample@example.org")
    missing = client.get("/api/v1/account/projects")
    assert missing.status_code == 401
    bad = client.post(
        "/api/v1/account/login",
        headers=ORIGIN,
        json={"email": "sample@example.org", "password": GOOD + "!"},
    )
    assert bad.status_code == 401
    headers = _login(client, "sample@example.org")
    account = client.get("/api/v1/account/session")
    assert account.status_code == 200
    assert account.json()["email"] == "sample@example.org"
    assert account.headers["cache-control"] == "no-store"
    # Session token is not stored plaintext in the database.
    with Session(db) as session:
        stored = session.scalar(select(UserSession))
        assert stored is not None
        assert stored.token_hash != client.cookies.get("__Host-aiseo_session")
        assert stored.csrf_hash != headers["X-CSRF-Token"]
    # Obtaining a new CSRF token invalidates the previous token.
    assert client.post("/api/v1/account/logout", headers=headers).status_code == 403
    headers["X-CSRF-Token"] = account.json()["csrf_token"]
    assert client.post("/api/v1/account/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/account/session").status_code == 401


def test_project_owner_isolation_csrf_and_challenge(api, monkeypatch):
    client, db = api
    _register(client, "first@example.org")
    first = _login(client, "first@example.org")
    fail = client.post("/api/v1/account/projects", json={"domain": "example.org"})
    assert fail.status_code == 403
    spoof = client.post(
        "/api/v1/account/projects",
        headers={"Origin": "https://evil.example", "X-CSRF-Token": first["X-CSRF-Token"]},
        json={"domain": "example.org"},
    )
    assert spoof.status_code == 403
    creation = client.post(
        "/api/v1/account/projects", headers=first, json={"domain": "example.org"}
    )
    assert creation.status_code == 201, creation.text
    project_id = creation.json()["id"]
    proof = creation.json()["verification_file_content"]
    assert proof.startswith("aiseoonline-verification=")
    assert len(proof) > 64
    assert creation.json()["verification_file_path"].startswith("/.well-known/")
    assert client.get("/api/v1/account/projects").json()[0]["verification_status"] == "unverified"

    # An attacker cannot read or mutate projects belonging to another account.
    assert client.post("/api/v1/account/logout", headers=first).status_code == 204
    _register(client, "second@example.org")
    second = _login(client, "second@example.org")
    assert client.get("/api/v1/account/projects").json() == []
    assert (
        client.post(f"/api/v1/account/projects/{project_id}/challenge", headers=second).status_code
        == 404
    )
    assert (
        client.post(f"/api/v1/account/projects/{project_id}/verify", headers=second).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/account/projects/{project_id}", headers=second).status_code == 404
    )

    assert client.post("/api/v1/account/logout", headers=second).status_code == 204
    first = _login(client, "first@example.org")
    fetched = []

    def fake_file(domain, expected_hash):
        fetched.append(domain)
        return expected_hash == accounts._hash(proof)

    monkeypatch.setattr(accounts, "verify_file", fake_file)
    verified = client.post(f"/api/v1/account/projects/{project_id}/verify", headers=first)
    assert verified.status_code == 200, verified.text
    assert verified.json()["verification_status"] == "verified"
    assert fetched == ["example.org"]
    with Session(db) as session:
        model = session.get(Project, UUID(verified.json()["id"]))
        assert model is not None and model.verification_token_hash is None
    assert client.delete(f"/api/v1/account/projects/{project_id}", headers=first).status_code == 204
    assert client.get("/api/v1/account/projects").json() == []


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "192.168.1.1",
        "169.254.169.254",
        "metadata.google.internal",
        "internal.local",
        "127.0.0.1",
        "example.org:8080",
        "evil.org/path",
        "user@public.example.org",
        "0x7f000001",
        "foo.test",
        "8.8.8.8",
    ],
)
def test_verification_domains_reject_internal_and_ambiguous_urls(host):
    with pytest.raises((ValueError, accounts.UnsafeTarget)):
        accounts._domain_name(host)


def test_file_verification_requires_exact_https_plain_text_no_redirect(monkeypatch):
    from aiseoonline_api.crawler.transport import HttpDocument

    expected = "aiseoonline-verification=" + "e" * 64

    def permitted(target, **kwargs):
        assert target.scheme == "https"
        assert target.host == "example.org"
        assert target.request_target == "/.well-known/aiseoonline-verification.txt"
        assert kwargs["max_bytes"] == 512
        assert kwargs["allowed_mime"] == ("text/plain",)
        return HttpDocument(200, "text/plain", "utf-8", None, (expected + "\n").encode())

    monkeypatch.setattr(accounts, "fetch_http", permitted)
    assert accounts.verify_file("example.org", accounts._hash(expected))
    assert not accounts.verify_file("example.org", accounts._hash(expected + "other"))
    monkeypatch.setattr(
        accounts,
        "fetch_http",
        lambda *args, **kw: HttpDocument(
            301, "text/plain", "utf-8", "https://elsewhere.example/", expected.encode()
        ),
    )
    assert not accounts.verify_file("example.org", accounts._hash(expected))
    monkeypatch.setattr(
        accounts,
        "fetch_http",
        lambda *args, **kw: HttpDocument(200, "text/html", "utf-8", None, expected.encode()),
    )
    assert not accounts.verify_file("example.org", accounts._hash(expected))


def test_verification_concurrency_saturation_fails_without_network(monkeypatch):
    class Busy:
        def acquire(self, *, blocking):
            assert blocking is False
            return False

    monkeypatch.setattr(accounts, "_VERIFY_SLOTS", Busy())
    monkeypatch.setattr(accounts, "fetch_http", lambda *a, **kw: pytest.fail("Unexpected fetch"))
    assert not accounts.verify_file("example.org", accounts._hash("proof"))


def test_project_deletion_refuses_unpurged_checkpoints(api):
    client, db = api
    _register(client, "worker@example.org")
    headers = _login(client, "worker@example.org")
    created = client.post(
        "/api/v1/account/projects", headers=headers, json={"domain": "example.org"}
    )
    assert created.status_code == 201
    identifier = created.json()["id"]
    with Session(db) as session, session.begin():
        session.add(AuditJob(project_id=UUID(identifier), status="queued"))
    response = client.delete(f"/api/v1/account/projects/{identifier}", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "retention_pending"


def test_anonymous_public_tools_and_security_headers(api):
    client, _ = api
    response = client.post("/api/v1/tools/meta", json={"url": "http://127.0.0.1/"})
    assert response.status_code == 422
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    # Public utilities retain no login requirement; they are limited by Redis.
    assert "/api/v1/tools/meta" in client.get("/api/v1/openapi.json").text


def test_production_registration_disabled_and_secure_origin_required():
    with pytest.raises(ValidationError, match="self-registration"):
        Settings(
            _env_file=None,
            environment="production",
            database_url="***db/app",
            redis_url="redis://localhost:6379",
            auth_registration_enabled=True,
        )
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(
            _env_file=None,
            environment="production",
            database_url="***db/app",
            redis_url="redis://localhost:6379",
            auth_web_origin="http://evil.example",
        )


def test_password_hash_is_salted_not_plaintext():
    first = accounts.password_hash(GOOD)
    second = accounts.password_hash(GOOD)
    assert first != second
    assert GOOD not in first
    assert accounts.password_matches(GOOD, first)
    assert not accounts.password_matches(GOOD + "!", first)


def test_account_metadata_export_and_deletion_revoke_sessions(api):
    client, db = api
    _register(client, "export@example.org")
    headers = _login(client, "export@example.org")
    made = client.post("/api/v1/account/projects", headers=headers, json={"domain": "example.org"})
    assert made.status_code == 201
    result = client.get("/api/v1/account/export")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["email"] == "export@example.org"
    assert result.json()["projects"][0]["verification_status"] == "unverified"
    assert "verification_file_content" not in result.text
    assert "password_hash" not in result.text
    assert "token_hash" not in result.text
    assert client.delete("/api/v1/account", headers=headers).status_code == 204
    assert client.get("/api/v1/account/session").status_code == 401
    with Session(db) as session:
        assert session.scalar(select(UserSession)) is None


def test_account_routes_fail_with_503_without_storage(monkeypatch):
    monkeypatch.setattr(accounts, "_throttle", lambda *args, **kwargs: True)
    app = create_app(Settings(_env_file=None, environment="test", database_url=None))
    with TestClient(app, base_url="https://testserver") as client:
        register = client.post(
            "/api/v1/account/register",
            headers=ORIGIN,
            json={"email": "a@example.org", "password": GOOD},
        )
        assert register.status_code == 404
        login = client.post(
            "/api/v1/account/login",
            headers=ORIGIN,
            json={"email": "a@example.org", "password": GOOD},
        )
        assert login.status_code == 503
        project = client.post(
            "/api/v1/account/projects", headers=ORIGIN, json={"domain": "example.org"}
        )
        assert project.status_code == 503


def test_account_cannot_delete_projects_with_orphanable_audit_checkpoints(api):
    client, engine = api
    _register(client, "retain@example.org")
    headers = _login(client, "retain@example.org")
    created = client.post(
        "/api/v1/account/projects", headers=headers, json={"domain": "example.org"}
    )
    assert created.status_code == 201
    with Session(engine) as session, session.begin():
        session.add(AuditJob(project_id=UUID(created.json()["id"]), owner_id=None, status="queued"))
    assert client.delete("/api/v1/account", headers=headers).status_code == 409
    assert client.get("/api/v1/account/projects").status_code == 200
