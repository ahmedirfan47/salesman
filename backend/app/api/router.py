from fastapi import APIRouter

from app.api.v1 import (
    accounts, agent, analytics, auth, billing, branches, console, conversations, customers, health, integrations, orders,
    platform, pricing, printing, products, prospects, reports, site, users, whatsapp, zatca, zones,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(site.router)
api_router.include_router(auth.router)
api_router.include_router(branches.router)
api_router.include_router(products.router)
api_router.include_router(users.router)
api_router.include_router(customers.router)
api_router.include_router(pricing.router)
api_router.include_router(orders.router)
api_router.include_router(accounts.router)
api_router.include_router(zatca.router)
api_router.include_router(integrations.router)
api_router.include_router(agent.router)
api_router.include_router(reports.router)
api_router.include_router(analytics.router)
api_router.include_router(prospects.router)
api_router.include_router(printing.router)
api_router.include_router(conversations.router)
api_router.include_router(zones.router)
api_router.include_router(billing.router)
api_router.include_router(platform.router)
api_router.include_router(console.router)
api_router.include_router(whatsapp.router)