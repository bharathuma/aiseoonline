"""Database-backed account journey and bounded query plan, with no external crawler."""

import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from aiseoonline_api import accounts
from aiseoonline_api.config import Settings
from aiseoonline_api.db.models import Project, User
from aiseoonline_api.main import create_app

ORIGIN = {"Origin": "http://testserver"}
PASSWORD = "fixture-password-long-enough"


@pytest.mark.integration
def test_account_project_proof_and_privacy_with_real_postgres_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = os.getenv("AISEO_TEST_DATABASE_URL")
    redis = os.getenv("AISEO_TEST_REDIS_URL")
    if not database or not redis:
        pytest.skip("Requires PostgreSQL and Redis integration services")
    email = "qa-" + uuid4().hex + "@example.org"
    domain = "qa-" + uuid4().hex + ".example.org"
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=database,
            redis_url=redis,
            auth_registration_enabled=True,
        )
    )
    engine = app.state.database_engine
    proof_checked: list[str] = []
    current_challenge = ""

    def fixed_transport(value: str, expected_hash: str) -> bool:
        proof_checked.append(value)
        return value == domain and expected_hash == accounts._hash(current_challenge)

    monkeypatch.setattr(accounts, "verify_file", fixed_transport)
    try:
        with TestClient(app, base_url="https://testserver") as client:
            created = client.post(
                "/api/v1/account/register",
                headers=ORIGIN,
                json={"email": email, "password": PASSWORD},
            )
            assert created.status_code == 201, created.text
            login = client.post(
                "/api/v1/account/login",
                headers=ORIGIN,
                json={"email": email, "password": PASSWORD},
            )
            assert login.status_code == 200, login.text
            headers = {**ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]}
            before = client.get("/api/v1/account/projects")
            assert before.status_code == 200 and before.json() == []
            project = client.post(
                "/api/v1/account/projects", headers=headers, json={"domain": domain}
            )
            assert project.status_code == 201, project.text
            project_id = project.json()["id"]
            current_challenge = project.json()["verification_file_content"]
            with Session(engine) as session:
                stored = session.scalar(select(Project).where(Project.id == uuid4()))
                assert stored is None
                assert session.scalar(
                    select(Project.verification_token_hash).where(Project.domain == domain)
                ) == accounts._hash(current_challenge)
            forbidden = client.post(
                f"/api/v1/account/projects/{project_id}/verify",
                headers={**headers, "X-CSRF-Token": "0" * 64},
            )
            assert forbidden.status_code == 403
            verified = client.post(f"/api/v1/account/projects/{project_id}/verify", headers=headers)
            assert verified.status_code == 200, verified.text
            assert verified.json()["verification_status"] == "verified"
            assert proof_checked == [domain]
            exported = client.get("/api/v1/account/export")
            assert exported.status_code == 200
            assert current_challenge not in exported.text
            assert exported.json()["projects"][0]["id"] == project_id
            assert (
                client.delete(f"/api/v1/account/projects/{project_id}", headers=headers).status_code
                == 204
            )
            assert client.delete("/api/v1/account", headers=headers).status_code == 204
            assert client.get("/api/v1/account/projects").status_code == 401
    finally:
        with Session(engine) as session, session.begin():
            # Cleanup is idempotent if a mid-test assertion aborts the account journey.
            user = session.scalar(select(User).where(User.email == email))
            if user is not None:
                session.delete(user)
        engine.dispose()


@pytest.mark.integration
def test_postgres_index_presence_and_bounded_project_query_plan() -> None:
    database = os.getenv("AISEO_TEST_DATABASE_URL")
    if not database:
        pytest.skip("Requires a migrated PostgreSQL integration service")
    from aiseoonline_api.db.session import create_database_engine

    engine = create_database_engine(
        Settings(_env_file=None, environment="test", database_url=database)
    )
    try:
        with engine.connect() as conn:
            names = set(
                conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
                ).scalars()
            )
            assert {
                "ix_projects_owner_id",
                "ix_audit_jobs_leases",
                "ix_rag_chunks_english_fts",
                "ix_user_sessions_user_id",
            } <= names
            # Analyze a single bounded query on CI fixture scale; never extrapolate
            # this planner timing to production traffic or table cardinalities.
            plan = conn.execute(
                text(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                    "SELECT id FROM projects WHERE owner_id = CAST(:owner AS uuid) "
                    "ORDER BY created_at DESC, id LIMIT 10"
                ),
                {"owner": str(uuid4())},
            ).scalar_one()
            measurement = {
                "environment": "ci_postgres_small_fixture",
                "query": "owned_projects_limit_10",
                "actual_execution_ms": plan[0]["Execution Time"],
                "plan_root": plan[0]["Plan"]["Node Type"],
                "rows": plan[0]["Plan"]["Actual Rows"],
                "required_indexes_present": True,
            }
            assert measurement["actual_execution_ms"] >= 0
            print("QA_DB_PLAN|" + json.dumps(measurement, sort_keys=True))
    finally:
        engine.dispose()
