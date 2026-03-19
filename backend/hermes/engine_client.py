"""gRPC client for communication with the .NET Hermes Engine.

This module provides a thin client that forwards engine operations
(monitoring, processing, plugin execution) to the .NET Engine service
via gRPC. The Python Web API handles CRUD and REST; the .NET Engine
handles all runtime processing.

Generated stubs are expected at hermes/generated/hermes_bridge_pb2*.py.
Run `python -m grpc_tools.protoc` to regenerate from protos/.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

ENGINE_GRPC_HOST = os.getenv("ENGINE_GRPC_HOST", "engine")
ENGINE_GRPC_PORT = int(os.getenv("ENGINE_GRPC_PORT", "50051"))

# Try to import gRPC; fall back to stub mode if unavailable.
_GRPC_AVAILABLE = False
try:
    import grpc  # type: ignore[import-untyped]

    _GRPC_AVAILABLE = True
except ImportError:
    logger.warning("grpcio not installed — EngineClient will run in stub mode")


class EngineClient:
    """Async gRPC client for the Hermes .NET Engine."""

    def __init__(
        self,
        host: str = ENGINE_GRPC_HOST,
        port: int = ENGINE_GRPC_PORT,
    ) -> None:
        self.host = host
        self.port = port
        self._channel: Any = None
        self._stub: Any = None

    async def connect(self) -> None:
        """Establish gRPC channel to the Engine service."""
        target = f"{self.host}:{self.port}"
        if not _GRPC_AVAILABLE:
            logger.info("Engine client in stub mode (grpcio not installed)")
            return

        try:
            from hermes.generated import hermes_bridge_pb2_grpc  # type: ignore

            self._channel = grpc.aio.insecure_channel(target)
            self._stub = hermes_bridge_pb2_grpc.HermesEngineServiceStub(
                self._channel
            )
            logger.info("Connected to Engine at %s", target)
        except ImportError:
            logger.warning(
                "Generated gRPC stubs not found — run proto codegen. "
                "Falling back to stub mode."
            )

    async def disconnect(self) -> None:
        """Close the gRPC channel."""
        if self._channel:
            await self._channel.close()
        logger.info("Engine client disconnected")

    @property
    def is_connected(self) -> bool:
        return self._stub is not None

    # ------------------------------------------------------------------
    # Pipeline lifecycle (delegated to .NET Engine)
    # ------------------------------------------------------------------

    async def activate_pipeline(
        self, pipeline_id: str, activated_by: str = "system"
    ) -> dict:
        """Request the Engine to activate a pipeline's monitoring."""
        if not self.is_connected:
            logger.info("Engine.activate_pipeline(%s) - stub", pipeline_id)
            return {"status": "stub", "pipeline_id": pipeline_id}

        from hermes.generated import hermes_bridge_pb2  # type: ignore

        response = await self._stub.ActivatePipeline(
            hermes_bridge_pb2.ActivateRequest(
                pipeline_id=pipeline_id,
                activated_by=activated_by,
            )
        )
        return {
            "success": response.success,
            "activation_id": response.activation_id,
            "error_message": response.error_message,
            "status": response.status,
        }

    async def deactivate_pipeline(
        self, pipeline_id: str, deactivated_by: str = "system", force: bool = False
    ) -> dict:
        """Request the Engine to deactivate a pipeline."""
        if not self.is_connected:
            logger.info("Engine.deactivate_pipeline(%s) - stub", pipeline_id)
            return {"status": "stub", "pipeline_id": pipeline_id}

        from hermes.generated import hermes_bridge_pb2  # type: ignore

        response = await self._stub.DeactivatePipeline(
            hermes_bridge_pb2.DeactivateRequest(
                pipeline_id=pipeline_id,
                deactivated_by=deactivated_by,
                force=force,
            )
        )
        return {
            "success": response.success,
            "in_flight_jobs": response.in_flight_jobs,
            "error_message": response.error_message,
        }

    # ------------------------------------------------------------------
    # Processing (delegated to .NET Engine)
    # ------------------------------------------------------------------

    async def reprocess_work_item(
        self,
        work_item_id: str,
        requested_by: str = "system",
        reason: str = "",
        start_from_step: int = 0,
        use_latest_recipe: bool = True,
    ) -> dict:
        """Request reprocessing of a work item."""
        if not self.is_connected:
            logger.info("Engine.reprocess_work_item(%s) - stub", work_item_id)
            return {"status": "stub", "work_item_id": work_item_id}

        from hermes.generated import hermes_bridge_pb2  # type: ignore

        response = await self._stub.ReprocessJob(
            hermes_bridge_pb2.ReprocessRequest(
                job_id=work_item_id,
                requested_by=requested_by,
                reason=reason,
                start_from_step=start_from_step,
                use_latest_recipe=use_latest_recipe,
            )
        )
        return {
            "success": response.success,
            "execution_id": response.execution_id,
            "error_message": response.error_message,
        }

    async def bulk_reprocess(
        self,
        work_item_ids: list[str],
        requested_by: str = "system",
        reason: str = "",
        use_latest_recipe: bool = True,
    ) -> dict:
        """Bulk reprocess multiple work items."""
        if not self.is_connected:
            logger.info("Engine.bulk_reprocess(%d items) - stub", len(work_item_ids))
            return {"status": "stub", "count": len(work_item_ids)}

        from hermes.generated import hermes_bridge_pb2  # type: ignore

        response = await self._stub.BulkReprocessJobs(
            hermes_bridge_pb2.BulkReprocessRequest(
                job_ids=work_item_ids,
                requested_by=requested_by,
                reason=reason,
                use_latest_recipe=use_latest_recipe,
            )
        )
        return {
            "accepted_count": response.accepted_count,
            "rejected_count": response.rejected_count,
        }

    # ------------------------------------------------------------------
    # Engine status
    # ------------------------------------------------------------------

    async def get_engine_status(self) -> dict:
        """Get the Engine's health and status."""
        if not self.is_connected:
            return {
                "status": "stub",
                "engine": "not_connected",
                "message": "gRPC client not yet connected",
            }

        from hermes.generated import hermes_bridge_pb2  # type: ignore

        response = await self._stub.GetEngineHealth(
            hermes_bridge_pb2.HealthRequest(include_details=True)
        )
        return {
            "status": response.status,
            "uptime_seconds": response.uptime_seconds,
            "active_pipelines": response.active_pipelines,
            "jobs_processing": response.jobs_processing,
            "jobs_queued": response.jobs_queued,
            "memory_used_mb": response.memory_used_mb,
            "engine_version": response.engine_version,
        }

    async def get_pipeline_status(self, pipeline_id: str) -> dict:
        """Get runtime status of a pipeline from the engine."""
        if not self.is_connected:
            return {"status": "stub", "pipeline_id": pipeline_id}

        from hermes.generated import hermes_bridge_pb2  # type: ignore

        response = await self._stub.GetPipelineStatus(
            hermes_bridge_pb2.StatusRequest(pipeline_id=pipeline_id)
        )
        return {
            "pipeline_id": response.pipeline_id,
            "status": response.status,
            "activation_id": response.activation_id,
            "active_jobs": response.active_jobs,
            "queued_jobs": response.queued_jobs,
            "total_jobs_processed": response.total_jobs_processed,
            "total_jobs_failed": response.total_jobs_failed,
        }
