"""Every router the app mounts, in the order it mounts them.

FastAPI answers with the first route that matches, so the order is behaviour. The auth
check in ``tests/integration/test_shared_trips.py`` walks this tuple too: a router left
out of it is a router nobody checked.
"""

from fastapi import APIRouter

from nexus.channels.web import (
    auth_api,
    chat_api,
    data_api,
    email_api,
    health_api,
    health_body_api,
    health_energy_api,
    health_food_api,
    home_api,
    imports_api,
    investments_api,
    ledger_api,
    money_api,
    ops_api,
    plan_api,
    settings_api,
    travel_api,
    views_api,
)

ROUTERS: tuple[APIRouter, ...] = (
    auth_api.router,
    auth_api.login_link_router,
    ledger_api.router,
    money_api.router,
    imports_api.router,
    plan_api.router,
    settings_api.router,
    home_api.router,
    chat_api.router,
    data_api.router,
    email_api.router,
    investments_api.router,
    health_api.router,
    health_body_api.router,
    health_energy_api.router,
    health_food_api.router,
    travel_api.router,
    travel_api.shared_router,
    ops_api.router,
    views_api.router,
)
