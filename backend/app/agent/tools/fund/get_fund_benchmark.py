"""get_fund_benchmark — 业绩比较基准原文、构成权重与相对基准的可核验指标."""

from typing import Annotated, Literal

from langchain_core.tools import tool
from pydantic import Field

from app.agent.tools.common import tool_result, validate_fund_code
from app.agent.tools.result import ToolResult
from app.services.fund_benchmark_service import fund_benchmark_service


@tool
@tool_result
async def get_fund_benchmark(
    fund_code: Annotated[str, Field(description="6位基金代码，保留前导零")],
    range_key: Annotated[Literal["1y", "3y"], Field(description="相对指标的观察区间，默认近3年")] = "3y",
) -> ToolResult:
    """查询基金的业绩比较基准原文、构成权重，以及基准可解析时的相对表现指标.

    benchmark_text是基金公司档案页的原话，parts是按权重拆出的指数段（百分点），
    cash_weight_pp是现金/存款段。这三项只要档案页取到了就有，是判断产品定位的依据。
    excess_return_ratio/beta/alpha_ratio/tracking_error_ratio与annual分年度对照，
    只在基准的每条成分指数都能取到收盘序列、且共同交易日足够时才有值；否则为空，
    并在unavailable_reason里说明缺哪一段。空值代表没算出来，不是0，不能补造。
    基准净值按权重合成（现金段按0收益），不是基金公司公布的基准序列。
    指标基于未复权净值与指数收盘价，不含分红与费用，不是投资者总回报。
    alpha按无风险利率0计算；目录外的指数（如中证800、恒生、纳斯达克100）不给相对指标。
    """
    data = await fund_benchmark_service.get_data(validate_fund_code(fund_code), range_key)
    return ToolResult.ok(
        data.model_dump(mode="json", exclude={"warnings"}),
        source="eastmoney_fund_profile+index_history",
        as_of=data.observed_to.isoformat() if data.observed_to else None,
        stale=data.stale,
        warnings=data.warnings,
    )
