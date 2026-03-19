"""API route modules for Hermes."""

from hermes.api.routes.definitions import router as definitions_router
from hermes.api.routes.instances import router as instances_router
from hermes.api.routes.pipelines import router as pipelines_router
from hermes.api.routes.system import router as system_router
from hermes.api.routes.work_items import router as work_items_router

__all__ = [
    "definitions_router",
    "instances_router",
    "pipelines_router",
    "work_items_router",
    "system_router",
]
