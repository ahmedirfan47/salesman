from fastapi import APIRouter

from app.api.v1 import (
    agent, auth, conversations, health, orders, pricing, printing,
    products, reports, users, whatsapp,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(products.router)
api_router.include_router(pricing.router)
api_router.include_router(orders.router)
api_router.include_router(agent.router)
api_router.include_router(reports.router)
api_router.include_router(printing.router)
api_router.include_router(conversations.router)
api_router.include_router(whatsapp.router)