"""Background worker that processes queued work items.

Uses a DB-based queue (prototype): polls for QUEUED work items and
dispatches them to the ProcessingOrchestrator.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vessel.domain.models.execution import ReprocessRequest, WorkItem
from vessel.domain.services.execution_dispatcher import ExecutionDispatcher
from vessel.domain.services.processing_orchestrator import ProcessingOrchestrator
from vessel.domain.services.snapshot_resolver import SnapshotResolver

logger = logging.getLogger(__name__)

# How often to poll for new work items (seconds)
_POLL_INTERVAL = 5

# Maximum work items to process concurrently
_MAX_CONCURRENT = 5


class ProcessingWorker:
    """Background task that picks up queued work items and processes them.

    Uses a simple DB-based queue:
    1. Poll for QUEUED work items
    2. Claim them by setting status to PROCESSING
    3. Call ProcessingOrchestrator.process_work_item()
    4. Handle PENDING reprocess requests

    For production, this should be replaced with a proper message queue
    (Redis, RabbitMQ, etc.).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    async def start(self) -> None:
        """Start the processing worker."""
        if self._running:
            logger.warning("Processing worker already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Processing worker started (max_concurrent=%d)", _MAX_CONCURRENT)

    async def stop(self) -> None:
        """Stop the processing worker."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Processing worker stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop for queued work items."""
        while self._running:
            try:
                await self._process_queued_items()
                await self._process_reprocess_requests()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in processing worker poll loop")

            await asyncio.sleep(_POLL_INTERVAL)

    async def _process_queued_items(self) -> None:
        """Pick up and process QUEUED work items."""
        async with self.session_factory() as db:
            # Find queued work items (limit to batch size)
            stmt = (
                select(WorkItem)
                .where(WorkItem.status == "QUEUED")
                .order_by(WorkItem.detected_at)
                .limit(_MAX_CONCURRENT)
                .with_for_update(skip_locked=True)
            )
            result = await db.execute(stmt)
            items = result.scalars().all()

            if not items:
                return

            logger.info("Found %d queued work items", len(items))

            # Claim items by updating status
            item_ids = [item.id for item in items]
            await db.execute(
                update(WorkItem)
                .where(WorkItem.id.in_(item_ids))
                .values(status="PROCESSING")
            )
            await db.commit()

        # Process each item concurrently (bounded by semaphore)
        tasks = [
            asyncio.create_task(self._process_item(item_id))
            for item_id in item_ids
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_item(self, work_item_id: uuid.UUID) -> None:
        """Process a single work item with concurrency control."""
        async with self._semaphore:
            try:
                async with self.session_factory() as db:
                    orchestrator = ProcessingOrchestrator(
                        db=db,
                        dispatcher=ExecutionDispatcher(),
                        snapshot_resolver=SnapshotResolver(db),
                    )
                    execution = await orchestrator.process_work_item(
                        work_item_id=work_item_id,
                        trigger_type="INITIAL",
                    )
                    await db.commit()
                    logger.info(
                        "Work item %s processed: %s",
                        work_item_id,
                        execution.status,
                    )
            except Exception:
                logger.exception("Failed to process work item %s", work_item_id)
                # Mark as FAILED
                try:
                    async with self.session_factory() as db:
                        item = await db.get(WorkItem, work_item_id)
                        if item:
                            item.status = "FAILED"
                            await db.commit()
                except Exception:
                    logger.exception(
                        "Failed to mark work item %s as FAILED", work_item_id
                    )

    async def _process_reprocess_requests(self) -> None:
        """Pick up and process PENDING reprocess requests."""
        async with self.session_factory() as db:
            stmt = (
                select(ReprocessRequest)
                .where(ReprocessRequest.status == "PENDING")
                .order_by(ReprocessRequest.requested_at)
                .limit(_MAX_CONCURRENT)
                .with_for_update(skip_locked=True)
            )
            result = await db.execute(stmt)
            requests = result.scalars().all()

            if not requests:
                return

            logger.info("Found %d pending reprocess requests", len(requests))

        for rr in requests:
            try:
                async with self.session_factory() as db:
                    orchestrator = ProcessingOrchestrator(
                        db=db,
                        dispatcher=ExecutionDispatcher(),
                        snapshot_resolver=SnapshotResolver(db),
                    )
                    await orchestrator.reprocess_work_item(rr.id)
                    await db.commit()
                    logger.info("Reprocess request %s completed", rr.id)
            except Exception:
                logger.exception("Failed to process reprocess request %s", rr.id)
