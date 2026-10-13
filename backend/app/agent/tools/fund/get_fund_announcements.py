"""按基金代码查询公开公告、定期报告及重大变更线索."""

from datetime import date
from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field, ValidationError

from app.agent.tools.common import ToolRuntimeError, tool_result, validate_fund_code
from app.agent.tools.result import ToolResult
from app.schemas.fund_disclosure import DisclosureCategory, FundAnnouncementsRequest
from app.services.fund_service import fund_service


@tool
@tool_result
async def get_fund_announcements(
    fund_code: Annotated[str, Field(description="6位基金代码，保留前导零")],
    category: Annotated[
        DisclosureCategory,
        Field(
            description="all全部、reports定期报告、major_changes重大变更线索、personnel人事、dividend分红、operation发行运作、sales销售、other其他"
        ),
    ] = "all",
    start_date: Annotated[date | None, Field(description="可选发布日期起始日YYYY-MM-DD，仅筛选当前页")] = None,
    end_date: Annotated[date | None, Field(description="可选发布日期截止日YYYY-MM-DD，仅筛选当前页")] = None,
    keyword: Annotated[
        str | None, Field(min_length=1, max_length=80, description="可选公告标题关键词，仅筛选当前页")
    ] = None,
    page: Annotated[int, Field(ge=1, le=1000, description="扫描页码，默认1；每页最多50条来源记录")] = 1,
    limit: Annotated[int, Field(ge=1, le=50, description="当前扫描页最多返回条数，默认20")] = 20,
    refresh: Annotated[bool, Field(description="true强制在线更新，false允许5分钟内成功缓存")] = False,
) -> ToolResult:
    """按基金代码获取公告或报告索引：标题、发布日期、真实原文链接及重大变更线索.

    reports查询定期报告；major_changes在全部公告中按标题规则识别经理变更、合同修改、
    清算合并转型、投资范围/费率/申赎变化等候选，待阅读原文核验，不证明已生效。
    只返回索引，不读取正文或PDF；发布日期不能当成事件生效日期。
    日期、关键词仅筛选当前50条扫描页。空匹配不证明无公告或无变更；看has_more/next_page。
    matched_count大于limit时可增大limit至50读完本页；不把局部结果称为全部公告。
    """
    code = validate_fund_code(fund_code)
    if keyword is not None and not keyword.strip():
        raise ToolRuntimeError("INVALID_ARGUMENT", "公告关键词不能只有空格")
    try:
        request = FundAnnouncementsRequest(
            fund_code=code,
            category=category,
            start_date=start_date,
            end_date=end_date,
            keyword=keyword.strip() if keyword else None,
            page=page,
            limit=limit,
            refresh=refresh,
        )
    except ValidationError:
        raise ToolRuntimeError("INVALID_ARGUMENT", "请核对基金代码、日期区间和分页参数；起始日不能晚于截止日")
    response = await fund_service.get_announcements(request)
    dates = [item.published_date for item in response.items if item.published_date is not None]
    return ToolResult.ok(
        response.model_dump(mode="json", exclude={"warnings"}),
        source="eastmoney_fund_announcements",
        as_of=max(dates).isoformat() if dates else None,
        warnings=response.warnings,
    )
