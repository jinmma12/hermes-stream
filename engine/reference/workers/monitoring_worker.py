"""Background worker that manages monitoring loops for active pipelines.

On startup, loads all ACTIVE pipeline activations from the database and
starts their monitoring loops. Handles new activations via periodic polling.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hermes.domain.models.monitoring import PipelineActivation
from hermes.domain.services.monitoring_engine import MonitoringEngine

logger = logging.getLogger(__name__)

# Poll interval for checking newly activated pipelines (seconds)
_NEW_ACTIVATION_POLL_INTERVAL = 10


class MonitoringWorker:
    """Background task that manages pipeline monitoring loops.

    Responsibilities:
    1. Load all ACTIVE/RUNNING pipeline activations on startup
    2. Start monitoring loops for each via MonitoringEngine
    3. Periodically check for new activations and start them
    4. Handle shutdown by stopping all monitors
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.engine = MonitoringEngine(session_factory)
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Start the monitoring worker."""
        if self._running:
            logger.warning("Monitoring worker already running")
            return

        self._running = True
        logger.info("Starting monitoring worker")

        # Load existing active activations
        await self._load_active_activations()

        # Start the background polling loop for new activations
        self._task = asyncio.create_task(self._poll_new_activations())
        logger.info(
            "Monitoring worker started with %d active monitors",
            len(self.engine.monitors),
        )

    async def stop(self) -> None:
        """Stop the monitoring worker and all monitors."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        await self.engine.stop_all()
        logger.info("Monitoring worker stopped")

    async def _load_active_activations(self) -> None:
        """Load all ACTIVE/RUNNING activations and start monitoring."""
        async with self.session_factory() as db:
            stmt = select(PipelineActivation).where(
                PipelineActivation.status.in_(["STARTING", "RUNNING"])
            )
            result = await db.execute(stmt)
            activations = result.scalars().all()

            for activation in activations:
                try:
                    await self.engine.start_monitoring(activation)
                except Exception:
                    logger.exception(
                        "Failed to start monitoring for activation %s",
                        activation.id,
                    )

    async def _poll_new_activations(self) -> None:
        """Periodically check for new activations that need monitoring."""
        while self._running:
            try:
                async with self.session_factory() as db:
                    stmt = select(PipelineActivation).where(
                        PipelineActivation.status == "STARTING"
                    )
                    result = await db.execute(stmt)
                    activations = result.scalars().all()

                    for activation in activations:
                        if activation.id not in self.engine.monitors:
                            try:
                                await self.engine.start_monitoring(activation)
                            except Exception:
                                logger.exception(
                                    "Failed to start monitoring for new activation %s",
                                    activation.id,
                                )

                    # Also check for stopped activations and clean up
                    stopped_ids: list[uuid.UUID] = []
                    for aid in list(self.engine.monitors.keys()):
                        act = await db.get(PipelineActivation, aid)
                        if act is None or act.status in ("STOPPED", "ERROR"):
                            stopped_ids.append(aid)

                    for aid in stopped_ids:
                        await self.engine.stop_monitoring(aid)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in activation polling loop")

            await asyncio.sleep(_NEW_ACTIVATION_POLL_INTERVAL)
