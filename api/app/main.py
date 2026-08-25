"""FastAPI entrypoint: lifespan, middleware, and router registration.

The lifespan resolves secrets *before* anything else touches configuration, then
starts the two periodic runners — the pipeline poller and the export worker.
Each takes a Redis lock per tick so that multiple API workers do not double-send
a notification or run the same report twice.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.secrets import resolve_secrets

_dev_mode = os.getenv("ENV", "production").lower() in ("development", "dev", "local")

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # Human-readable in dev; JSON in production for log aggregators
        structlog.dev.ConsoleRenderer() if _dev_mode else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.DEBUG if _dev_mode else logging.INFO
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

# Route stdlib logging (uvicorn, SQLAlchemy) through structlog
logging.basicConfig(
    format="%(message)s",
    level=logging.DEBUG if _dev_mode else logging.INFO,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: run startup tasks before serving, cleanup after."""
    import asyncio  # noqa: PLC0415

    from app.services.export_runner import run_export_worker_loop  # noqa: PLC0415
    from app.services.pipeline_poller import run_poller_loop  # noqa: PLC0415

    resolve_secrets()
    logger.info("api.startup", version="0.1.0")
    # Two periodic runners, each guarded by its own Redis lock: the poller
    # watches pipeline connections and sends notifications, the export worker
    # executes report runs and expires their results.
    tasks = [
        asyncio.create_task(run_poller_loop()),
        asyncio.create_task(run_export_worker_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("api.shutdown")


app = FastAPI(
    title="Power BI Platform API",
    version="0.1.0",
    lifespan=lifespan,
)


# catch_unhandled_exceptions must be added BEFORE CORSMiddleware so that
# Starlette places CORS outermost in the stack:
#   ServerErrorMiddleware → CORS → catch → ExceptionMiddleware → Router
#
# Starlette prepends each add_middleware call and then wraps in reverse, so the
# LAST middleware added ends up outermost. Adding catch first, then CORS, means
# CORS is outermost. This ensures the JSONResponse(500) we return flows back
# through CORSMiddleware and picks up the Access-Control-Allow-Origin header.
@app.middleware("http")
async def catch_unhandled_exceptions(request: Request, call_next):  # type: ignore[type-arg]  # noqa: ANN001, ANN201
    """Turn an unhandled exception into a 500 that still carries CORS headers."""
    try:
        return await call_next(request)
    except Exception as exc:
        logger.exception("api.unhandled_exception", path=request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
from app.routers import (  # noqa: E402
    admin,
    audit,
    auth,
    bi_connections,
    changes,
    dashboards,
    data,
    data_dict,
    data_pipelines,
    embed,
    exports,
    favorites,
    notifications,
    pages,
    pipeline_notifications,
    portal,
    search,
    users,
    warehouses,
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(users.router, tags=["Users"])
app.include_router(portal.router, tags=["Portal"])
app.include_router(dashboards.router, tags=["Dashboards"])
app.include_router(embed.router, prefix="/embed", tags=["Embed"])
app.include_router(pages.router, tags=["Pages"])
app.include_router(bi_connections.router, tags=["BI Connections"])
app.include_router(data_pipelines.router, tags=["Data Pipelines"])
app.include_router(pipeline_notifications.router, tags=["Pipeline Notifications"])
app.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
app.include_router(warehouses.router, tags=["Warehouses"])
app.include_router(data_dict.router, tags=["Data Dictionary"])
app.include_router(data.router, prefix="/data", tags=["Data"])
app.include_router(exports.router, prefix="/exports", tags=["Exports"])
app.include_router(changes.router, tags=["Changes"])
app.include_router(audit.router, prefix="/audit", tags=["Audit"])
app.include_router(favorites.router, tags=["Favorites"])
app.include_router(search.router, prefix="/search", tags=["Search"])


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    """Return API health status."""
    return {"status": "ok"}
