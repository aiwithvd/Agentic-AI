"""FastAPI application factory and entry point."""

from __future__ import annotations

import logging
import logging.config
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agent.api.middleware import RequestIDMiddleware
from agent.api.routers import health, threads
from agent.cache.redis_client import close_redis_pool, get_redis_pool
from agent.db.engine import close_engine, get_engine, get_session_factory
from agent.graph import workflow
from agent.settings import get_settings


def _configure_logging(log_level: str) -> None:
    """Set up structured JSON logging for the whole application."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": "logging.Formatter",
                    "fmt": (
                        '{"time":"%(asctime)s","level":"%(levelname)s",'
                        '"logger":"%(name)s","message":"%(message)s"}'
                    ),
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                }
            },
            "root": {"level": log_level, "handlers": ["console"]},
        }
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup and shutdown of all shared resources.

    Startup order:
      1. Configure logging
      2. Warm SQLAlchemy connection pool
      3. Create LangGraph AsyncPostgresSaver, run setup(), compile graph
      4. Warm Redis connection pool

    Shutdown order (reverse):
      4. Close Redis pool
      3. AsyncPostgresSaver context manager cleans up its own pool
      2. Close SQLAlchemy engine
    """
    settings = get_settings()
    _configure_logging(settings.log_level)
    logger = logging.getLogger("agent.startup")

    # 1. SQLAlchemy pool
    logger.info("startup: warming SQLAlchemy connection pool")
    get_engine()
    get_session_factory()

    # 2. LangGraph checkpoint + compile graph with checkpointer
    logger.info("startup: initialising LangGraph AsyncPostgresSaver")
    async with AsyncPostgresSaver.from_conn_string(
        str(settings.checkpoint_database_url)
    ) as checkpointer:
        await checkpointer.setup()  # idempotent — creates checkpoint tables
        app.state.graph = workflow.compile(checkpointer=checkpointer)
        logger.info("startup: LangGraph graph compiled with checkpointer")

        # 3. Redis pool
        logger.info("startup: warming Redis connection pool")
        get_redis_pool()

        logger.info("startup: all resources ready")
        yield  # ── application handles requests here ──

        # Shutdown
        logger.info("shutdown: closing Redis pool")
        await close_redis_pool()

    # AsyncPostgresSaver pool is closed by its own context manager above
    logger.info("shutdown: closing SQLAlchemy engine")
    await close_engine()
    logger.info("shutdown: complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="LangGraph Agent API",
        description=(
            "FastAPI serving layer for a LangGraph conversational agent "
            "with PostgreSQL persistence and Redis rate limiting."
        ),
        version="0.0.1",
        lifespan=lifespan,
        # Disable interactive docs in production to reduce attack surface
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
    )

    # ── Middleware (outermost registered = last executed on request) ──────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)

    # ── Routers ───────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(threads.router)

    return app


# Module-level app instance so uvicorn can reference it as
# "agent.api.app:app"
app = create_app()


def run() -> None:
    """Entrypoint used by the `serve` script in pyproject.toml."""
    settings = get_settings()
    uvicorn.run(
        "agent.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.app_env == "development",
        log_level=settings.log_level.lower(),
        access_log=False,  # handled by RequestIDMiddleware
    )
