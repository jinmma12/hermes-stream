"""API route modules for Vessel."""

from vessel.api.routes.definitions import router as definitions_router
from vessel.api.routes.instances import router as instances_router
from vessel.api.routes.pipelines import router as pipelines_router
from vessel.api.routes.system import router as system_router
from vessel.api.routes.work_items import router as work_items_router

__all__ = [
    "definitions_router",
    "instances_router",
    "pipelines_router",
    "work_items_router",
    "system_router",
]
