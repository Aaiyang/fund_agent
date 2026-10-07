"""API v1 路由装配.

本模块创建主 API 路由，并挂载 auth、chatbot、funds、watchlist、portfolio、
accounts、transactions、持仓导入以及 agent 占位这些子路由。
"""

from fastapi import APIRouter

from app.api.v1.accounts import router as accounts_router
from app.api.v1.agent import router as agent_router
from app.api.v1.auth import router as auth_router
from app.api.v1.auto_invest import router as auto_invest_router
from app.api.v1.chatbot import router as chatbot_router
from app.api.v1.funds import router as funds_router
from app.api.v1.imports import router as holding_imports_router
from app.api.v1.indexes import router as indexes_router
from app.api.v1.markets import router as markets_router
from app.api.v1.portfolio import router as portfolio_router
from app.api.v1.transactions import router as transactions_router
from app.api.v1.watchlist import router as watchlist_router
from app.core.logging import logger

api_router = APIRouter()

# 挂载子路由
api_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
api_router.include_router(chatbot_router, prefix="/chatbot", tags=["Chatbot"])
api_router.include_router(funds_router, prefix="/funds", tags=["Funds"])
api_router.include_router(indexes_router, prefix="/indexes", tags=["Indexes"])
api_router.include_router(markets_router, prefix="/markets", tags=["Markets"])
api_router.include_router(watchlist_router, prefix="/watchlist", tags=["Watchlist"])
api_router.include_router(portfolio_router, prefix="/portfolio", tags=["Portfolio"])
api_router.include_router(accounts_router, prefix="/accounts", tags=["Accounts"])
api_router.include_router(transactions_router, prefix="/transactions", tags=["Transactions"])
api_router.include_router(holding_imports_router, prefix="/holding-imports", tags=["Holding Imports"])
api_router.include_router(auto_invest_router, prefix="/auto-invest", tags=["Auto Invest"])
api_router.include_router(agent_router, prefix="/agent", tags=["Agent"])


@api_router.get("/health")
async def health_check():
    """健康检查端点.

    Returns:
        dict: 健康状态信息。
    """
    logger.info("health_check_called")
    return {"status": "healthy", "version": "1.0.0"}
