"""研究工作流入口：只声明任务，由主图校验和执行."""

from typing import Literal

from langchain_core.tools import tool

from app.agent.tools.result import ToolResult
from app.schemas.research import AllocationAction, ResearchIntent, ResearchRequest


@tool(args_schema=ResearchRequest)
async def start_research(
    intent: ResearchIntent,
    mode: Literal["standard", "deep"] = "standard",
    fund_queries: list[str] | None = None,
    account_id: int | None = None,
    action: AllocationAction | None = None,
    proposed_amount: float | None = None,
    sector_query: str | None = None,
    stock_symbol: str | None = None,
    strategy: Literal["single", "multi_role"] = "single",
) -> str:
    """启动基金研究、组合诊断、建仓/加减仓、板块或股票研究，只读不交易.

    基金名称/代码放fund_queries，最多三只，服务端先解析并在歧义时等待Top3人工选择。
    明确比较两到三只基金用fund_comparison，分别分析多只基金仍用fund_research；同一代码不构成对比。
    深入研究用deep，普通完整研究用standard；纯净值、行情、概念查询不用此工具。
    用户明确要求多角色、多智能体或多agent研究时strategy用multi_role；默认single。
    multi_role暂支持基金、基金对比、组合诊断及配置分析，不能用于股票或板块研究。
    account_id只用本轮用户明确指定的账户编号，不从名称猜编号；公开基金研究无需账户或已有持仓。
    allocation_analysis的action可为build/increase/reduce/exit/compare。
    proposed_amount仅使用用户明确提供的人民币金额；未提供不猜数，不构成交易授权。
    sector_research用sector_query传本轮原文板块名称或BK代码；多匹配会要求确认。
    stock_research用stock_symbol传本轮明确的带市场前缀股票代码，如sh600519、hk00700、usAAPL。
    只有股票名称或裸代码先询问市场和代码，不自行推断。股票和板块研究不传fund_queries。
    复合请求分步处理，当前研究完成后再开始下一项，不和导入操作同批提出。
    """
    request = ResearchRequest(
        intent=intent,
        mode=mode,
        strategy=strategy,
        fund_queries=fund_queries or [],
        account_id=account_id,
        action=action,
        proposed_amount=proposed_amount,
        sector_query=sector_query,
        stock_symbol=stock_symbol,
    )
    return ToolResult.ok(request.model_dump(mode="json"), source="task_router").to_text()
