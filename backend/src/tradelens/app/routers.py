"""Every router the API serves, in one list."""

from fastapi import APIRouter

from tradelens.modules.analysis.router import router as dev_chart_router
from tradelens.modules.monitoring.router import router as monitoring_router

ROUTERS: tuple[APIRouter, ...] = (monitoring_router,)
# Mounted only when APP_ENV=development (task 1.10 dev chart; never in staging or production).
DEV_ROUTERS: tuple[APIRouter, ...] = (dev_chart_router,)
