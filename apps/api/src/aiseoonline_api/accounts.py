"""Credentialed project management with explicit CSRF, ownership and file proof.

Public checks remain anonymous. Production self-registration and private scans stay off
until email verification and paid-operation entitlement are implemented.
"""

import hashlib
import hmac
import ipaddress
import re
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aiseoonline_api.config import Settings
from aiseoonline_api.crawler.transport import fetch_http
from aiseoonline_api.crawler.urls import CrawlError, UnsafeTarget, normalize_url
from aiseoonline_api.db.models import AuditJob, Project, User, UserSession
from aiseoonline_api.errors import error_response

router = APIRouter(tags=["Private accounts and projects"])
_EMAIL = re.compile(r"^[a-z0-9][a-z0-9._+\-]{0,62}@[a-z0-9][a-z0-9.\-]{0,250}\.[a-z]{2,24}$")
_DOMAIN = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)
COOKIE = "__Host-aiseo_session"
_VERIFY_SLOTS = threading.BoundedSemaphore(2)
_PROOF_PATH = "/.well-known/aiseoonline-verification.txt"
_DAY = timedelta(hours=24)
_ACCOUNT_THROTTLE = """
local n=redis.call('INCR',KEYS[1])
if n==1 then redis.call('EXPIRE',KEYS[1],3600) end
return n<=tonumber(ARGV[1])
"""


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=6, max_length=320)
    password: str = Field(min_length=12, max_length=128)


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str = Field(min_length=4, max_length=253)


class ProjectView(BaseModel):
    id: UUID
    domain: str
    verification_status: str
    verified_at: datetime | None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def password_hash(password: str) -> str:
    if not 12 <= len(password) <= 128 or not password.isascii():
        raise ValueError("Password must contain 12–128 ASCII characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$" + salt.hex() + "$" + digest.hex()


def password_matches(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$16384$"):
        return False
    try:
        _, _, salt, expected = stored.split("$")
        result = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(result, bytes.fromhex(expected))
    except (ValueError, UnicodeError):
        return False


def _email(value: str) -> str:
    cleaned = value.strip().lower()
    if not _EMAIL.fullmatch(cleaned):
        raise ValueError("Invalid email format")
    return cleaned


def _origin(request: Request) -> bool:
    settings: Settings = request.app.state.settings
    accepted = {settings.auth_web_origin}
    if settings.environment == "test":
        accepted.add("http://testserver")
    return request.headers.get("origin") in accepted


def _engine(request: Request):
    return request.app.state.database_engine


def _response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    result = error_response(request, status, code, message)
    result.headers["Cache-Control"] = "no-store"
    return result


def _throttle(request: Request, label: str, limit: int) -> bool:
    settings: Settings = request.app.state.settings
    if settings.redis_url is None:
        return False
    remote = request.client.host if request.client else "unknown"
    # Hash identifiers so Redis keys never contain addresses or usernames.
    key = "auth:" + _hash(f"{label}:{remote}")
    try:
        with Redis.from_url(
            settings.require_redis_url(), socket_connect_timeout=0.6, socket_timeout=0.6
        ) as client:
            return bool(client.eval(_ACCOUNT_THROTTLE, 1, key, limit))
    except (RedisError, OSError, TimeoutError):
        return False


def _session(request: Request, session: Session) -> tuple[User, UserSession] | None:
    raw = request.cookies.get(COOKIE, "")
    if not re.fullmatch(r"[0-9a-f]{64}", raw):
        return None
    value = session.scalar(
        select(UserSession).where(
            UserSession.token_hash == _hash(raw), UserSession.expires_at > datetime.now(UTC)
        )
    )
    if value is None:
        return None
    user = session.get(User, value.user_id)
    if user is None or user.password_hash is None:
        return None
    return user, value


def _require(request: Request, session: Session, *, write: bool) -> User | None:
    result = _session(request, session)
    if result is None:
        return None
    user, active = result
    if write:
        submitted = request.headers.get("x-csrf-token", "")
        if (
            not _origin(request)
            or not re.fullmatch(r"[0-9a-f]{64}", submitted)
            or not hmac.compare_digest(_hash(submitted), active.csrf_hash)
        ):
            return None
    return user


def _project(session: Session, project_id: UUID, owner: UUID) -> Project | None:
    return session.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == owner)
    )


def _view(project: Project) -> ProjectView:
    return ProjectView(
        id=project.id,
        domain=project.domain,
        verification_status=project.verification_status,
        verified_at=project.verified_at,
    )


def _challenge(project: Project) -> str:
    # Proof token is disclosed once; persist its hash, not its plaintext.
    value = "aiseoonline-verification=" + secrets.token_hex(32)
    project.verification_token_hash = _hash(value)
    project.verification_status = "unverified"
    project.verified_at = None
    return value


def _domain_name(raw: str) -> str:
    domain = raw.strip().rstrip(".").lower()
    if not _DOMAIN.fullmatch(domain) or len(domain) > 253:
        raise ValueError("Invalid domain")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError("A domain name rather than an IP address is required")
    # Reuse SSRF URL policy to reject reserved and numeric hosts; verification is HTTPS only.
    address = normalize_url("https://" + domain + _PROOF_PATH)
    if address.host != domain:
        raise ValueError("Domain normalization mismatch")
    return domain


def verify_file(domain: str, expected_hash: str) -> bool:
    """Pinned public HTTPS proof, 2 concurrent calls, no redirects, 512 bytes."""
    target = normalize_url("https://" + _domain_name(domain) + _PROOF_PATH)
    if not _VERIFY_SLOTS.acquire(blocking=False):
        return False
    try:
        document = fetch_http(
            target,
            max_bytes=512,
            deadline=time.monotonic() + 7,
            connect_timeout=3,
            dns_timeout=2,
            allowed_mime=("text/plain",),
        )
    finally:
        _VERIFY_SLOTS.release()
    if document.status != 200 or document.location or document.content_type != "text/plain":
        return False
    try:
        content = document.body.decode("utf-8").strip()
    except UnicodeDecodeError:
        return False
    if len(content) > 96:
        return False
    return hmac.compare_digest(_hash(content), expected_hash)


@router.post("/account/register", status_code=201)
def register(request: Request, body: Credentials) -> Response:
    settings: Settings = request.app.state.settings
    if settings.environment == "production" or not settings.auth_registration_enabled:
        return _response(request, 404, "not_found", "Registration is unavailable.")
    if _engine(request) is None:
        return _response(request, 503, "service_unavailable", "Registration unavailable.")
    if not _origin(request) or not _throttle(request, "register", 4):
        return _response(request, 429, "rate_limited", "Registration is unavailable.")
    try:
        email = _email(body.email)
        secret = password_hash(body.password)
        with Session(_engine(request)) as session, session.begin():
            if session.scalar(select(User.id).where(User.email == email)):
                return _response(request, 409, "account_exists", "Registration is unavailable.")
            session.add(User(email=email, password_hash=secret))
    except (ValueError, IntegrityError):
        return _response(request, 409, "registration_failed", "Registration is unavailable.")
    return Response(status_code=201, headers={"Cache-Control": "no-store"})


@router.post("/account/login")
def login(request: Request, body: Credentials) -> Response:
    if not _origin(request) or not _throttle(request, "login", 10):
        return _response(request, 429, "rate_limited", "Login temporarily unavailable.")
    if _engine(request) is None:
        return _response(request, 503, "service_unavailable", "Login unavailable.")
    try:
        email = _email(body.email)
    except ValueError:
        return _response(request, 401, "unauthorized", "Invalid credentials.")
    raw = secrets.token_hex(32)
    csrf = secrets.token_hex(32)
    with Session(_engine(request)) as session, session.begin():
        user = session.scalar(select(User).where(User.email == email))
        if user is None or not password_matches(body.password, user.password_hash):
            # Equalize the expensive password check for missing accounts.
            if user is None:
                password_matches(body.password, _DUMMY_HASH)
            return _response(request, 401, "unauthorized", "Invalid credentials.")
        session.add(
            UserSession(
                user_id=user.id,
                token_hash=_hash(raw),
                csrf_hash=_hash(csrf),
                expires_at=datetime.now(UTC) + _DAY,
            )
        )
    response = JSONResponse({"csrf_token": csrf}, headers={"Cache-Control": "no-store"})
    response.set_cookie(
        COOKIE,
        raw,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=int(_DAY.total_seconds()),
    )
    return response


@router.get("/account/session")
def account_session(request: Request) -> Response:
    if _engine(request) is None:
        return _response(request, 503, "service_unavailable", "Account unavailable.")
    with Session(_engine(request)) as session, session.begin():
        item = _session(request, session)
        if item is None:
            return _response(request, 401, "unauthorized", "Authentication required.")
        user, active = item
        csrf = secrets.token_hex(32)
        active.csrf_hash = _hash(csrf)
        result = {"id": str(user.id), "email": user.email, "csrf_token": csrf}
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.post("/account/logout")
def logout(request: Request) -> Response:
    if _engine(request) is None:
        return _response(request, 503, "service_unavailable", "Account unavailable.")
    with Session(_engine(request)) as session, session.begin():
        user = _require(request, session, write=True)
        if user is None:
            return _response(request, 403, "forbidden", "Session or CSRF check failed.")
        item = _session(request, session)
        assert item is not None
        session.delete(item[1])
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


@router.get("/account/projects", response_model=list[ProjectView])
def list_projects(request: Request) -> list[ProjectView] | Response:
    if _engine(request) is None:
        return _response(request, 503, "service_unavailable", "Projects unavailable.")
    with Session(_engine(request)) as session:
        user = _require(request, session, write=False)
        if user is None:
            return _response(request, 401, "unauthorized", "Authentication required.")
        rows = session.scalars(
            select(Project)
            .where(Project.owner_id == user.id)
            .order_by(Project.created_at.desc(), Project.id)
            .limit(10)
        ).all()
        return [_view(item) for item in rows]


@router.post("/account/projects", status_code=201)
def create_project(request: Request, body: ProjectInput) -> Response:
    if not _throttle(request, "projects", 15):
        return _response(request, 429, "rate_limited", "Project request limit reached.")
    if _engine(request) is None:
        return _response(request, 503, "service_unavailable", "Projects unavailable.")
    try:
        domain = _domain_name(body.domain)
    except (UnsafeTarget, ValueError):
        return _response(request, 422, "invalid_domain", "A public DNS hostname is required.")
    try:
        with Session(_engine(request)) as session, session.begin():
            user = _require(request, session, write=True)
            if user is None:
                return _response(request, 403, "forbidden", "Session or CSRF check failed.")
            # Serialize concurrent project creations for this owner before checking quota.
            session.scalar(select(User.id).where(User.id == user.id).with_for_update())
            count = session.scalar(
                select(func.count()).select_from(Project).where(Project.owner_id == user.id)
            )
            if count is None or count >= 10:
                return _response(request, 429, "project_quota", "Project quota reached.")
            project = Project(owner_id=user.id, domain=domain)
            proof = _challenge(project)
            session.add(project)
            session.flush()
            identifier = str(project.id)
    except IntegrityError:
        return _response(request, 409, "project_exists", "Project already registered.")
    return JSONResponse(
        {
            "id": identifier,
            "domain": domain,
            "verification_status": "unverified",
            "verification_file_path": _PROOF_PATH,
            "verification_file_content": proof,
        },
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/account/projects/{project_id}/challenge")
def rotate_challenge(request: Request, project_id: UUID) -> Response:
    if _engine(request) is None:
        return _response(request, 503, "service_unavailable", "Projects unavailable.")
    with Session(_engine(request)) as session, session.begin():
        user = _require(request, session, write=True)
        if user is None:
            return _response(request, 403, "forbidden", "Session or CSRF check failed.")
        project = _project(session, project_id, user.id)
        if project is None:
            return _response(request, 404, "not_found", "Project unavailable.")
        proof = _challenge(project)
    return JSONResponse(
        {"verification_file_path": _PROOF_PATH, "verification_file_content": proof},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/account/projects/{project_id}/verify", response_model=ProjectView)
def verify_project(request: Request, project_id: UUID) -> ProjectView | Response:
    if _engine(request) is None:
        return _response(request, 503, "service_unavailable", "Projects unavailable.")
    if not _throttle(request, "verification", 12):
        return _response(request, 429, "rate_limited", "Verification temporarily unavailable.")
    with Session(_engine(request)) as session:
        user = _require(request, session, write=True)
        if user is None:
            return _response(request, 403, "forbidden", "Session or CSRF check failed.")
        project = _project(session, project_id, user.id)
        if project is None:
            return _response(request, 404, "not_found", "Project unavailable.")
        proof_hash = project.verification_token_hash
        domain = project.domain
    if not proof_hash:
        return _response(request, 409, "no_challenge", "Request a new verification challenge.")
    try:
        proven = verify_file(domain, proof_hash)
    except CrawlError:
        proven = False
    if not proven:
        return _response(request, 422, "verification_failed", "Verification file not confirmed.")
    # Recheck the owner and the challenge after the potentially slow remote request.
    with Session(_engine(request)) as session, session.begin():
        user = _require(request, session, write=True)
        if user is None:
            return _response(request, 403, "forbidden", "Session or CSRF check failed.")
        project = _project(session, project_id, user.id)
        if project is None or project.verification_token_hash != proof_hash:
            return _response(
                request, 409, "verification_changed", "Verification challenge changed."
            )
        project.verification_status = "verified"
        project.verified_at = datetime.now(UTC)
        project.verification_token_hash = None
        result = _view(project)
    return result


@router.delete("/account/projects/{project_id}", status_code=204)
def delete_project(request: Request, project_id: UUID) -> Response:
    if _engine(request) is None:
        return _response(request, 503, "service_unavailable", "Projects unavailable.")
    with Session(_engine(request)) as session, session.begin():
        user = _require(request, session, write=True)
        if user is None:
            return _response(request, 403, "forbidden", "Session or CSRF check failed.")
        project = _project(session, project_id, user.id)
        if project is None:
            return _response(request, 404, "not_found", "Project unavailable.")
        if session.scalar(select(AuditJob.id).where(AuditJob.project_id == project_id).limit(1)):
            # LangGraph PostgreSQL checkpoints require separate archival/purge handling.
            return _response(
                request, 409, "retention_pending", "Audit checkpoint cleanup is required."
            )
        session.delete(project)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/account/export")
def export_account(request: Request) -> Response:
    """Minimal account and project metadata export; no private audit content is sent."""
    if _engine(request) is None:
        return _response(request, 503, "service_unavailable", "Account unavailable.")
    with Session(_engine(request)) as session:
        user = _require(request, session, write=False)
        if user is None:
            return _response(request, 401, "unauthorized", "Authentication required.")
        projects = session.scalars(
            select(Project)
            .where(Project.owner_id == user.id)
            .order_by(Project.created_at.desc(), Project.id)
            .limit(10)
        ).all()
        account = {
            "id": str(user.id),
            "email": user.email,
            "projects": [_view(item).model_dump(mode="json") for item in projects],
        }
    return JSONResponse(
        account,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="account-metadata.json"',
        },
    )


@router.delete("/account", status_code=204)
def delete_account(request: Request) -> Response:
    """Delete only accounts without audit checkpoints; never claim external purge."""
    if _engine(request) is None:
        return _response(request, 503, "service_unavailable", "Account unavailable.")
    with Session(_engine(request)) as session, session.begin():
        user = _require(request, session, write=True)
        if user is None:
            return _response(request, 403, "forbidden", "Session or CSRF check failed.")
        active_jobs = session.scalar(
            select(AuditJob.id)
            .join(Project, AuditJob.project_id == Project.id)
            .where(Project.owner_id == user.id)
            .limit(1)
        )
        if active_jobs is not None:
            return _response(
                request,
                409,
                "retention_pending",
                "Audit checkpoint cleanup is required before account deletion.",
            )
        session.delete(user)
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


# Verified offline constant for unknown-user password timing; not a real credential.
_DUMMY_HASH = "scrypt$16384$" + "00" * 16 + "$" + "00" * 32
