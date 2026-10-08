"""工具注册表：Agent 可装配的工具集合.

分组与领域边界一致——fund、portfolio、market 适配器都只委托各自的领域
服务；system 组是通用能力（联网搜索、人工确认、在线日历）。``graph/agent.py`` 绑定
``DEFAULT_AGENT_TOOLS``；将来按会话裁剪工具集只需要改这里。
"""

from langchain_core.tools import BaseTool

from app.agent.tools.ask_human import ask_human
from app.agent.tools.duckduckgo_search import duckduckgo_search_tool
from app.agent.tools.get_calendar import get_calendar
from app.agent.tools.fund import (
    get_fund_holdings,
    get_fund_history,
    get_fund_snapshot,
    search_funds,
)
from app.agent.tools.market import get_market_context
from app.agent.tools.user_persona import propose_user_profile_update
from app.agent.tools.portfolio import (
    get_portfolio,
    get_positions,
    get_holding_import,
    request_holding_import_confirmation,
)

# 工具集版本：仅当工具增删或 Schema 变化时升级（KV Cache 全局前缀组成部分）
TOOLS_VERSION = "v4"

# 基金域
FUND_TOOLS: list[BaseTool] = [search_funds, get_fund_snapshot, get_fund_history, get_fund_holdings]

# 组合域
PORTFOLIO_TOOLS: list[BaseTool] = [
    get_portfolio,
    get_positions,
    get_holding_import,
    request_holding_import_confirmation,
]

# 行情域
MARKET_TOOLS: list[BaseTool] = [get_market_context]

# 通用系统工具
SYSTEM_TOOLS: list[BaseTool] = [ask_human, duckduckgo_search_tool, get_calendar, propose_user_profile_update]

DEFAULT_AGENT_TOOLS: list[BaseTool] = [
    *FUND_TOOLS,
    *PORTFOLIO_TOOLS,
    *MARKET_TOOLS,
    *SYSTEM_TOOLS,
]
