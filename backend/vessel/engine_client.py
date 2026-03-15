"""gRPC client for communication with the .NET Hermes Engine.

This module provides a thin client that forwards engine operations
(monitoring, processing, plugin execution) to the .NET Engine service
via gRPC. The Python Web API handles CRUD and REST; the .NET Engine
handles all runtime processing.

TODO: Generate gRPC stubs from protos/ and implement real calls.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

ENGINE_GRPC_HOST = os.getenv("ENGINE_GRPC_HOST", "engine")
ENGINE_GRPC_PORT = int(os.getenv("ENGINE_GRPC_PORT", "50051"))


class EngineClient:
    """Async gRPC client for the Hermes .NET Engine."""

    def __init__(
        self,
        host: str = ENGINE_GRPC_HOST,
        port: int = ENGINE_GRPC_PORT,
    ) -> None:
        self.host = host
        self.port = port
        self._channel = None  # TODO: grpc.aio.insecure_channel

    async def connect(self) -> None:
        """Establish gRPC channel to the Engine service."""
        target = f"{self.host}:{self.port}"
        logger.info("Connecting to Engine at %s (stub - gRPC not yet implemented)", target)
        # TODO: self._channel = grpc.aio.insecure_channel(target)
        # TODO: self._stub = engine_pb2_grpc.EngineServiceStub(self._channel)

    async def disconnect(self) -> None:
        """Close the gRPC channel."""
        if self._channel:
            await self._channel.close()
        logger.info("Engine client disconnected")

    # ------------------------------------------------------------------
    # Pipeline lifecycle (delegated to .NET Engine)
    # ------------------------------------------------------------------

    async def activate_pipeline(self, pipeline_id: str) -> dict:
        """Request the Engine to activate a pipeline's monitoring."""
        logger.info("Engine.activate_pipeline(%s) - stub", pipeline_id)
        # TODO: return await self._stub.ActivatePipeline(request)
        return {"status": "stub", "pipeline_id": pipeline_id}

    async def deactivate_pipeline(self, pipeline_id: str) -> dict:
        """Request the Engine to deactivate a pipeline."""
        logger.info("Engine.deactivate_pipeline(%s) - stub", pipeline_id)
        # TODO: return await self._stub.DeactivatePipeline(request)
        return {"status": "stub", "pipeline_id": pipeline_id}

    # ------------------------------------------------------------------
    # Processing (delegated to .NET Engine)
    # ------------------------------------------------------------------

    async def reprocess_work_item(self, work_item_id: str) -> dict:
        """Request reprocessing of a work item."""
        logger.info("Engine.reprocess_work_item(%s) - stub", work_item_id)
        # TODO: return await self._stub.ReprocessWorkItem(request)
        return {"status": "stub", "work_item_id": work_item_id}

    # ------------------------------------------------------------------
    # Engine status
    # ------------------------------------------------------------------

    async def get_engine_status(self) -> dict:
        """Get the Engine's health and status."""
        logger.info("Engine.get_engine_status() - stub")
        # TODO: return await self._stub.GetStatus(request)
        return {
            "status": "stub",
            "engine": "not_connected",
            "message": "gRPC client not yet implemented",
        }
