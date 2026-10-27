"""工具注册表：Agent 可装配的工具集合.

分组与领域边界一致——fund、portfolio、market 适配器都只委托各自的领域
服务；system 组是通用能力（联网搜索、人工确认、在线日历）。``graph/agent.py`` 绑定
``DEFAULT_AGENT_TOOLS``；将来按会话裁剪工具集只需要改这里。
"""

from langchain_core.tools import BaseTool

from app.agent.tools.ask_human import ask_human
from app.agent.tools.duckduckgo_search import duckduckgo_search_tool
from app.agent.tools.get_calendar import get_calendar
from app.agent.tools.load_skill import load_skill
from app.agent.tools.start_research import start_research
from app.agent.tools.fund import (
    get_fund_holdings,
    get_fund_history,
    get_fund_snapshot,
    get_fund_sectors,
    get_fund_managers,
    get_fund_announcements,
    get_fund_analysis_data,
    get_fund_benchmark,
    get_fund_comparison_data,
    get_sector_market,
    search_funds,
    resolve_fund_for_analysis,
)
from app.agent.tools.market import get_market_context, get_realtime_market, get_market_events, get_stock_analysis_data
from app.agent.tools.user_persona import propose_user_profile_update
from app.agent.tools.portfolio import (
    get_portfolio,
    get_portfolio_snapshot,
    get_positions,
    get_holding_import,
    start_holding_import,
    request_holding_import_confirmation,
    identify_event_portfolio_links,
)
from app.agent.tools.watchlist import get_watchlist

# 工具集版本：仅当工具增删或 Schema 变化时升级（KV Cache 全局前缀组成部分）
TOOLS_VERSION = "v21"

# 基金域
FUND_TOOLS: list[BaseTool] = [
    search_funds,
    resolve_fund_for_analysis,
    get_fund_snapshot,
    get_fund_history,
    get_fund_holdings,
    get_fund_sectors,
    get_sector_market,
    get_fund_managers,
    get_fund_announcements,
    get_fund_analysis_data,
    get_fund_benchmark,
    get_fund_comparison_data,
]

# 组合域
PORTFOLIO_TOOLS: list[BaseTool] = [
    get_portfolio,
    get_portfolio_snapshot,
    get_positions,
    get_holding_import,
    start_holding_import,
    request_holding_import_confirmation,
    identify_event_portfolio_links,
    get_watchlist,
]

# 行情域
MARKET_TOOLS: list[BaseTool] = [get_market_context, get_realtime_market, get_market_events, get_stock_analysis_data]

# 通用系统工具
SYSTEM_TOOLS: list[BaseTool] = [
    ask_human,
    duckduckgo_search_tool,
    get_calendar,
    propose_user_profile_update,
    load_skill,
    start_research,
]

DEFAULT_AGENT_TOOLS: list[BaseTool] = [
    *FUND_TOOLS,
    *PORTFOLIO_TOOLS,
    *MARKET_TOOLS,
    *SYSTEM_TOOLS,
]
