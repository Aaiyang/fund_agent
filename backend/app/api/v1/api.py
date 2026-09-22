"""API v1 router configuration.

This module sets up the main API router and includes all sub-routers for
auth, chatbot, funds, watchlist, portfolio, accounts, transactions,
holding imports and the agent placeholder.
"""

from fastapi import APIRouter

from app.api.v1.accounts import router as accounts_router
from app.api.v1.agent import router as agent_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chatbot import router as chatbot_router
from app.api.v1.funds import router as funds_router
from app.api.v1.imports import router as holding_imports_router
from app.api.v1.indexes import router as indexes_router
from app.api.v1.portfolio import router as portfolio_router
from app.api.v1.transactions import router as transactions_router
from app.api.v1.watchlist import router as watchlist_router
from app.core.logging import logger

api_router = APIRouter()

# Include routers
api_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
api_router.include_router(chatbot_router, prefix="/chatbot", tags=["Chatbot"])
api_router.include_router(funds_router, prefix="/funds", tags=["Funds"])
api_router.include_router(indexes_router, prefix="/indexes", tags=["Indexes"])
api_router.include_router(watchlist_router, prefix="/watchlist", tags=["Watchlist"])
api_router.include_router(portfolio_router, prefix="/portfolio", tags=["Portfolio"])
api_router.include_router(accounts_router, prefix="/accounts", tags=["Accounts"])
api_router.include_router(transactions_router, prefix="/transactions", tags=["Transactions"])
api_router.include_router(holding_imports_router, prefix="/holding-imports", tags=["Holding Imports"])
api_router.include_router(agent_router, prefix="/agent", tags=["Agent"])


@api_router.get("/health")
async def health_check():
    """Health check endpoint.

    Returns:
        dict: Health status information.
    """
    logger.info("health_check_called")
    return {"status": "healthy", "version": "1.0.0"}
