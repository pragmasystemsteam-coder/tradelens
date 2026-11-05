"""Every router the API serves, in one list."""

from fastapi import APIRouter

from tradelens.modules.monitoring.router import router as monitoring_router

ROUTERS: tuple[APIRouter, ...] = (monitoring_router,)
