import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import redis
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import func, select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.aptly_client import AptlyClient, AptlyError, get_aptly_client
from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.limiter import limiter
from app.logging_config import configure_logging, correlation_id_var
from app.metrics import ACTIVE_SERVERS, REQUEST_DURATION, REQUESTS_TOTAL, UNREACHABLE_SERVERS, registry
from app.models import Job, JobStatus, Server, ServerStatus
from app.routers import (
    activation_keys,
    audit_logs,
    auth,
    branding,
    compliance,
    content_views,
    docs_content,
    enrollment,
    errata,
    host_groups,
    instance_settings,
    jobs,
    lifecycle_environments,
    products,
    repositories,
    servers,
    sites,
    trends,
    users,
    version,
)

configure_logging()
logger = logging.getLogger("groundctl.main")


def _run_migrations() -> None:
    # Alembic migrations (ROADMAP Phase 7) replace Base.metadata.create_all()
    # — app/alembic/env.py reads settings.database_url directly, same
    # source of truth as everywhere else in the app. alembic.command.upgrade
    # is the in-process equivalent of `alembic upgrade head`, no subprocess.
    alembic_cfg = AlembicConfig("alembic.ini")
    command.upgrade(alembic_cfg, "head")


def _reap_stuck_jobs() -> None:
    # ROADMAP.md Phase 2: mark `running` jobs orphaned on API-process
    # startup. A Job can be left `running` if the worker that was executing
    # it crashed/restarted without ever reaching a terminal state. Cross-
    # reference against Celery's live task registry: any `running` Job
    # whose celery_task_id isn't currently active on any worker was
    # orphaned. One-shot check on startup, not a recurring task — a job
    # stuck for longer than the API process's uptime is caught on the next
    # restart (see docs/limitations.md).
    try:
        active = celery_app.control.inspect().active() or {}
    except Exception:  # noqa: BLE001 - Celery/Redis unreachable at startup must not block boot
        return
    active_task_ids = {task["id"] for tasks in active.values() for task in tasks}

    db = SessionLocal()
    try:
        stuck = db.execute(select(Job).where(Job.status == JobStatus.running)).scalars()
        for job in stuck:
            if job.celery_task_id not in active_task_ids:
                job.status = JobStatus.failed
                job.log_output = "orphaned — worker restarted while job was running"
                job.finished_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_migrations()
    _reap_stuck_jobs()
    yield


app = FastAPI(title="Groundctl", lifespan=lifespan)

app.state.limiter = limiter
# slowapi's handler is typed narrowly for RateLimitExceeded; Starlette's
# add_exception_handler wants the broader Exception signature — a known
# stub mismatch between the two libraries, not a real type error here.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Reads X-Request-ID if the caller supplied one, else generates a
    uuid4. Set on a contextvar (app/logging_config.py) so every log line
    emitted while handling this request carries it, and echoed back as a
    response header so callers can correlate their own logs against ours.
    """

    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        response.headers["X-Request-ID"] = correlation_id
        return response


app.add_middleware(CorrelationIdMiddleware)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start
        # route.path (not request.url.path) so "/servers/{id}" doesn't
        # fragment into one label series per UUID — matched_route is only
        # set once FastAPI's routing has resolved the endpoint.
        route = request.scope.get("route")
        path = route.path if route is not None else request.url.path
        REQUESTS_TOTAL.labels(method=request.method, path=path, status=response.status_code).inc()
        REQUEST_DURATION.labels(method=request.method, path=path).observe(duration)
        return response


app.add_middleware(MetricsMiddleware)

# Every resource router lives under /api — NOT cosmetic. The web UI (below)
# is a client-side-routed SPA whose own page paths are the *same* strings as
# several of these resource names (/servers, /jobs, /errata, /sites,
# /activation-keys — a page and a "list X" endpoint are naturally named
# alike). Before this prefix, app.include_router mounted those endpoints at
# the bare path, which FastAPI matches BEFORE the SPA catch-all StaticFiles
# mount ever sees the request (see SPAStaticFiles below) — so a hard
# refresh/deep link on e.g. /servers hit the real `GET /servers` API
# endpoint (401 JSON with no Authorization header) instead of ever reaching
# the SPA. Namespacing every resource router under /api removes the
# collision entirely: no SPA route will ever again share a path with an API
# route by coincidence. /health and /metrics stay unprefixed (infra
# endpoints — monitoring/orchestration tooling conventionally expects them
# at the root, and neither collides with an SPA page anyway).
#
# Every aptly interaction in this codebase goes through a named AptlyClient
# method with a fixed, specific purpose (see app/aptly_client.py). No router
# or endpoint here proxies or forwards arbitrary aptly calls — do not add one.
api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(repositories.router, prefix="/repositories", tags=["repositories"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(content_views.router, prefix="/content-views", tags=["content-views"])
api_router.include_router(
    lifecycle_environments.router, prefix="/lifecycle-environments", tags=["lifecycle-environments"]
)
api_router.include_router(servers.router, prefix="/servers", tags=["servers"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(compliance.router, prefix="/compliance", tags=["compliance"])
api_router.include_router(trends.router, prefix="/trends", tags=["trends"])
api_router.include_router(errata.router, prefix="/errata", tags=["errata"])
api_router.include_router(host_groups.router, prefix="/host-groups", tags=["host-groups"])
api_router.include_router(activation_keys.router, prefix="/activation-keys", tags=["activation-keys"])
# No Depends(get_current_user) anywhere in this router — the
# activation-key token IS the authentication. See enrollment.py. (Not the
# only unauthenticated router in the app — branding and version are too,
# for their own reasons noted at each include_router call below.)
api_router.include_router(enrollment.router, prefix="/enrollment", tags=["enrollment"])
api_router.include_router(sites.router, prefix="/sites", tags=["sites"])
api_router.include_router(audit_logs.router, prefix="/audit-logs", tags=["audit-logs"])
# /api/docs, NOT /docs — that's FastAPI's own Swagger UI, unprefixed and
# unaffected (see the /api-prefixing note above). Serves docs/*.md, synced
# alongside app/ into /opt/groundctl/docs by sync_app_code.
api_router.include_router(docs_content.router, prefix="/docs", tags=["docs"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
# GET /api/branding/logo and /favicon are the two unauthenticated
# endpoints in this router (see branding.py) — a <link rel="icon">/<img>
# tag has no way to attach a Bearer token, same reasoning as
# enrollment.py's ssh-public-key endpoint.
api_router.include_router(branding.router, prefix="/branding", tags=["branding"])
api_router.include_router(instance_settings.router, prefix="/instance-settings", tags=["instance-settings"])
# Unauthenticated for the same reason as branding above — polled by every
# logged-in tab's header, and the version number itself isn't sensitive.
api_router.include_router(version.router, prefix="/version", tags=["version"])
app.include_router(api_router)


@app.get("/health", tags=["health"])
def health(response: Response, aptly: AptlyClient = Depends(get_aptly_client)):
    """Unauthenticated — health checks need to work before/without a valid
    JWT (standard practice) and carry no sensitive data. Each check is a
    real operation, not a ping: an unreachable dependency must show up
    here without crashing the endpoint itself (that's the whole point).
    Returns 503 if any check fails, so a monitor can gate on status code
    alone. Not wired into systemd ExecStartPre — see docs/limitations.md.

    aptly is injected via Depends (not called directly) so tests can
    override it via app.dependency_overrides — a real bug caught during
    Phase 7 test-writing: calling get_aptly_client() directly bypassed the
    override mechanism entirely, silently making the negative-path test
    untestable.
    """
    checks: dict[str, str] = {}

    db = SessionLocal()
    try:
        db.execute(select(1))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report, don't propagate
        checks["database"] = f"error: {exc}"
    finally:
        db.close()

    try:
        aptly.ping()
        checks["aptly"] = "ok"
    except AptlyError as exc:
        checks["aptly"] = f"error: {exc}"

    try:
        redis.from_url(settings.redis_url, socket_connect_timeout=3).ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report, don't propagate
        checks["redis"] = f"error: {exc}"

    ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "degraded", "checks": checks}


@app.get("/metrics", tags=["health"])
def metrics():
    # Unauthenticated, matching Prometheus's own scrape-endpoint convention
    # — metrics aren't secrets, and requiring auth would need Prometheus
    # itself to carry a token, an unusual scrape-config burden.
    db = SessionLocal()
    try:
        ACTIVE_SERVERS.set(
            db.execute(select(func.count()).select_from(Server).where(Server.status != ServerStatus.unreachable)).scalar()
        )
        UNREACHABLE_SERVERS.set(
            db.execute(select(func.count()).select_from(Server).where(Server.status == ServerStatus.unreachable)).scalar()
        )
    finally:
        db.close()
    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


class SPAStaticFiles(StaticFiles):
    """Starlette's StaticFiles(html=True) only falls back to index.html for
    a *directory*-shaped miss (e.g. /servers/ -> /servers/index.html) — a
    real bug found via live testing during Phase 8 (a bare client-side route
    like /login has no on-disk collision at all, and StaticFiles.get_response
    *raises* HTTPException(404) rather than returning a 404 Response,
    breaking every deep link/hard-refresh in the SPA). Overriding
    get_response to catch that and retry against index.html gives
    react-router's client-side routing the fallback the html=True flag was
    assumed to already provide.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # Only fall back for route-shaped paths (no file extension on the
            # last segment) — a genuinely missing asset (bad JS/CSS
            # reference) must stay a real 404, not silently become index.html.
            if exc.status_code != 404 or "." in path.rsplit("/", 1)[-1]:
                raise
            return await super().get_response("index.html", scope)


# Web UI (ROADMAP Phase 8) — the built React SPA (ui/ -> `npm run build` ->
# ui/dist/, synced to app/static by scripts/lib/app.sh). Mounted at "/" and
# LAST, after every API router: StaticFiles only ever handles a request that
# didn't match an API route above it, so this can never shadow the API. The
# directory is optional at import time — a checkout with no UI build yet
# (e.g. this repo before `npm run build` has ever run, or a pure-API
# deployment) must still boot the API cleanly.
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/", SPAStaticFiles(directory=_static_dir, html=True), name="ui")
