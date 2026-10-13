"""固定公开基金披露来源的异步请求、解析与有界重试."""

import asyncio
import re
from datetime import date
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.schemas.fund_disclosure import (
    FundAnnouncement,
    FundAnnouncementPage,
    FundManagerHistoryData,
    FundManagerIdentity,
    FundManagerPeriod,
)

_SEMAPHORE = asyncio.Semaphore(4)
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_CATEGORY_NAMES = {"1": "operation", "2": "dividend", "3": "reports", "4": "personnel", "5": "sales", "6": "other"}
_CHANGE_PATTERNS = {
    "manager_change": r"基金经理.*(?:变更|调整|离任|增聘)|(?:变更|调整|离任|增聘).*基金经理",
    "contract_change": r"(?:修改|修订|变更|调整).*基金合同|基金合同.*(?:修改|修订|变更|调整)",
    "termination_or_liquidation": r"清算|清盘|基金合同终止|终止.*基金合同",
    "fund_merger_or_transformation": r"基金.*(?:合并|转型)|(?:合并|转型).*基金",
    "investment_scope_change": r"(?:变更|调整|修改).*投资范围|投资范围.*(?:变更|调整|修改)",
    "investment_strategy_change": r"(?:变更|调整|修改).*投资策略|投资策略.*(?:变更|调整|修改)",
    "name_or_benchmark_change": r"(?:变更|调整|修改|更名).*(?:基金名称|业绩比较基准)|(?:基金名称|业绩比较基准).*(?:变更|调整|修改|更名)",
    "management_or_custodian_change": r"(?:变更|更换).*(?:基金管理人|基金托管人)|(?:基金管理人|基金托管人).*(?:变更|更换)",
    "fee_change": r"(?:调整|降低|变更).*费率|费率.*(?:调整|降低|变更)",
    "subscription_redemption_change": r"(?:暂停|恢复|限制).*?(?:申购|赎回)|(?:申购|赎回).*?(?:暂停|恢复|限制)",
}


class FundDisclosureUnavailable(ValueError):
    """来源不可识别，不伪装成基金没有经理或公告."""


def validate_code(code: str) -> None:
    """在数据源边界重复校验，不接受地址或非ASCII代码."""
    if not re.fullmatch(r"[0-9]{6}", code):
        raise ValueError("无效基金代码")


def _date(value: Any) -> date | None:
    """只解析来源日期，不用当前日期代填缺失."""
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:T|\s|$)", value.strip())
    if not match:
        return None
    try:
        return date.fromisoformat(match[1])
    except ValueError:
        return None


def parse_manager_history(html: str, code: str) -> FundManagerHistoryData:
    """只读取指定基金历任表，不混入页面中的经理其他基金经历."""
    validate_code(code)
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text() if soup.title else ""
    if not re.search(r"[（(]" + code + r"[)）]", title):
        raise FundDisclosureUnavailable("基金经理页面身份不匹配")
    table = None
    for candidate in soup.select("table"):
        rows = candidate.select("tr")
        if rows and [cell.get_text(strip=True) for cell in rows[0].select("th,td")] == [
            "起始期",
            "截止期",
            "基金经理",
            "任职期间",
            "任职回报",
        ]:
            table = candidate
            break
    if table is None:
        raise FundDisclosureUnavailable("未识别到基金历任经理表")
    periods: list[FundManagerPeriod] = []
    for row in table.select("tr")[1:]:
        cells = row.select("td")
        if len(cells) != 5:
            raise FundDisclosureUnavailable("经理历史表结构不完整")
        start, end_text = _date(cells[0].get_text(strip=True)), cells[1].get_text(strip=True)
        current = end_text == "至今"
        end = None if current else _date(end_text)
        if start is None or (not current and end is None) or (end is not None and end < start):
            raise FundDisclosureUnavailable("经理任职日期不可核验")
        managers = []
        for anchor in cells[2].select("a[href]"):
            href = str(anchor.get("href", ""))
            parsed = urlparse(href)
            match = re.fullmatch(r"/manager/([0-9]+)\.html", parsed.path)
            name = anchor.get_text(strip=True)
            if match and name and parsed.hostname in {None, "fund.eastmoney.com"}:
                managers.append(FundManagerIdentity(name=name, manager_id=match[1]))
        if not managers:
            raise FundDisclosureUnavailable("经理姓名或来源标识缺失")
        period = FundManagerPeriod(
            managers=managers,
            start_date=start,
            end_date=end,
            is_current=current,
            source_duration=cells[3].get_text(strip=True) or None,
        )
        if period not in periods:
            periods.append(period)
    if not periods or len(periods) > 200:
        raise FundDisclosureUnavailable("经理历史为空或超过安全上限")
    return FundManagerHistoryData(
        fund_code=code,
        periods=sorted(periods, key=lambda row: row.start_date, reverse=True),
        source_url=f"https://fundf10.eastmoney.com/jjjl_{code}.html",
    )


def parse_announcement_page(payload: Any, code: str, page: int, page_size: int) -> FundAnnouncementPage:
    """核验页码和基金身份；仅由真实报告ID构建来源链接."""
    validate_code(code)
    if not isinstance(payload, dict) or payload.get("ErrCode") != 0:
        raise FundDisclosureUnavailable("公告数据源返回错误")
    total, rows = payload.get("TotalCount"), payload.get("Data")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
        or not isinstance(rows, list)
        or payload.get("PageIndex") != page
        or payload.get("PageSize") != page_size
        or len(rows) > page_size
    ):
        raise FundDisclosureUnavailable("公告分页结构不可核验")
    if not rows and (page - 1) * page_size < total:
        raise FundDisclosureUnavailable("公告页缺失")
    expected = max(0, min(page_size, total - (page - 1) * page_size))
    if len(rows) > expected:
        raise FundDisclosureUnavailable("公告条数超过声明的分页总量")
    items, invalid = [], 0
    for row in rows:
        if not isinstance(row, dict):
            invalid += 1
            continue
        if row.get("FUNDCODE") != code:
            raise FundDisclosureUnavailable("公告基金代码不匹配")
        report_id, title = row.get("ID"), row.get("TITLE")
        if (
            not isinstance(report_id, str)
            or not re.fullmatch(r"AN[0-9]{10,30}", report_id)
            or not isinstance(title, str)
            or not title.strip()
        ):
            invalid += 1
            continue
        category = str(row.get("NEWCATEGORY", ""))
        hints = [name for name, pattern in _CHANGE_PATTERNS.items() if re.search(pattern, title)]
        items.append(
            FundAnnouncement(
                announcement_id=report_id,
                fund_code=code,
                title=title.strip(),
                published_date=_date(row.get("PUBLISHDATE")),
                category=_CATEGORY_NAMES.get(category, "unknown"),
                source_category=category or None,
                url=f"https://fund.eastmoney.com/gonggao/{code},{report_id}.html",
                major_change_hints=hints,
            )
        )
    return FundAnnouncementPage(
        fund_code=code,
        page=page,
        page_size=page_size,
        total=total,
        items=items,
        invalid_items=invalid,
        missing_items=expected - len(rows),
    )


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, OSError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=3),
    reraise=True,
)
async def _get(url: str, *, referer: str, params: dict[str, Any] | None = None) -> httpx.Response:
    """有界公开请求；地址仅由内部固定来源和校验代码构造."""
    async with _SEMAPHORE:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params, headers={**_HEADERS, "Referer": referer})
            response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise FundDisclosureUnavailable("披露响应超过安全上限")
    return response


async def fetch_manager_history(code: str) -> FundManagerHistoryData:
    """获取一次基金历任页面，解析不在网络重试范围内."""
    validate_code(code)
    url = f"https://fundf10.eastmoney.com/jjjl_{code}.html"
    response = await _get(url, referer=url)
    # 网站页面为UTF-8；不依赖主机系统编码。
    return parse_manager_history(response.content.decode("utf-8"), code)


async def fetch_announcements(code: str, category: int, page: int, page_size: int) -> FundAnnouncementPage:
    """获取指定代码的一页公告；调用参数再次有界校验."""
    validate_code(code)
    if category not in range(7) or not 1 <= page <= 1000 or not 1 <= page_size <= 50:
        raise ValueError("公告查询参数超出范围")
    response = await _get(
        "https://api.fund.eastmoney.com/f10/JJGG",
        referer=f"https://fundf10.eastmoney.com/jjgg_{code}.html",
        params={"fundcode": code, "pageIndex": page, "pageSize": page_size, "type": category},
    )
    result = parse_announcement_page(response.json(), code, page, page_size)
    if category and any(row.source_category != str(category) for row in result.items):
        raise FundDisclosureUnavailable("公告类别与查询类别不匹配")
    return result
