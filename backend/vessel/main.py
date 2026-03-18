"""FastAPI application entrypoint for Hermes.

This is the Web API layer (Python/FastAPI). Engine functions (monitoring,
processing, plugin execution, NiFi integration) are delegated to the
.NET Engine service via gRPC. See engine/ for the .NET implementation
and engine/reference/ for the original Python reference implementations.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vessel.api.routes.definitions import router as definitions_router
from vessel.api.routes.instances import router as instances_router
from vessel.api.routes.pipelines import router as pipelines_router
from vessel.api.routes.system import router as system_router
from vessel.api.routes.work_items import router as work_items_router
from vessel.api.websocket import router as websocket_router
from vessel.domain.models.base import Base
from vessel.engine_client import EngineClient
from vessel.infrastructure.database.session import async_engine

logger = logging.getLogger(__name__)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# gRPC client for .NET Engine
_engine_client: EngineClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    global _engine_client

    # Startup
    logger.info("Hermes Web API starting up...")

    # Initialize database tables
    async with async_engine.begin() as conn:
        # Import all models so they are registered with Base
        import vessel.domain.models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")

    # Connect to .NET Engine via gRPC
    _engine_client = EngineClient()
    await _engine_client.connect()
    logger.info("Engine client connected (gRPC)")

    # Store engine client in app state for route handlers
    app.state.engine_client = _engine_client

    yield

    # Shutdown
    logger.info("Hermes Web API shutting down...")
    if _engine_client:
        await _engine_client.disconnect()
    await async_engine.dispose()
    logger.info("Hermes Web API shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Hermes",
        description="Lightweight data processing platform with per-job tracking",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(definitions_router)
    app.include_router(instances_router)
    app.include_router(pipelines_router)
    app.include_router(work_items_router)
    app.include_router(system_router)
    app.include_router(websocket_router)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "name": "Hermes",
            "tagline": "The messenger for your data.",
            "version": "0.1.0",
            "docs": "/docs",
        }

    return app


# Application instance for uvicorn
app = create_app()
