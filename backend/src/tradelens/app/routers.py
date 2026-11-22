"""Every router the API serves, in one list."""

from fastapi import APIRouter

from tradelens.modules.accounts.router import dev_router as dev_accounts_router
from tradelens.modules.accounts.router import router as accounts_router
from tradelens.modules.analysis.router import router as dev_chart_router
from tradelens.modules.charts.router import router as charts_router
from tradelens.modules.market_data.router import router as market_router
from tradelens.modules.monitoring.router import router as monitoring_router
from tradelens.modules.realtime.router import router as realtime_router
from tradelens.modules.scanner.router import router as scanner_router
from tradelens.modules.watchlists.router import router as watchlists_router

ROUTERS: tuple[APIRouter, ...] = (
    monitoring_router,
    accounts_router,
    market_router,
    scanner_router,
    charts_router,
    watchlists_router,
    realtime_router,
)
# Mounted only when APP_ENV=development (task 1.10 dev chart; task 3.2 dev verification link;
# never in staging or production).
DEV_ROUTERS: tuple[APIRouter, ...] = (dev_chart_router, dev_accounts_router)
