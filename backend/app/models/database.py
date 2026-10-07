"""应用用到的全部数据库模型."""

from app.models.fund import Fund, FundNav
from app.models.holding_import import HoldingImport, HoldingImportItem
from app.models.job import BackgroundJob
from app.models.market import IndexQuote
from app.models.portfolio import PortfolioAccount, PortfolioPosition, Transaction
from app.models.session import Session
from app.models.thread import Thread
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistGroup, WatchlistGroupItem

__all__ = [
    "BackgroundJob",
    "Fund",
    "FundNav",
    "HoldingImport",
    "HoldingImportItem",
    "IndexQuote",
    "PortfolioAccount",
    "PortfolioPosition",
    "Session",
    "Thread",
    "Transaction",
    "User",
    "Watchlist",
    "WatchlistGroup",
    "WatchlistGroupItem",
]
