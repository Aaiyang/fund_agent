"""AKShare rank rows carry Chinese column names; searching them by English keys silently matched nothing."""

from app.integrations.fund_data.akshare_provider import match_records
from app.integrations.fund_data.models import FundExternalRecord
from app.integrations.fund_data.normalizer import normalize_fund_record

RAW_ROWS = [
    {
        "基金代码": "011452",
        "基金简称": "华泰柏瑞质量成长混合C",
        "单位净值": "3.129",
        "日期": "2026-09-18",
        "日增长率": "0.36",
    },
    {
        "基金代码": "512888",
        "基金简称": "国泰中证全指证券公司ETF联接A",
        "单位净值": "1.204",
        "日期": "2026-09-18",
        "日增长率": "-1.2",
    },
    {"基金代码": None, "基金简称": "脏数据行"},
]

INDEX = [record for row in RAW_ROWS if (record := normalize_fund_record(row)) is not None]


def test_index_is_built_from_chinese_columns() -> None:
    assert [record.fund_code for record in INDEX] == ["011452", "512888"]


def test_fuzzy_name_search_matches_substring() -> None:
    assert [record.fund_code for record in match_records(INDEX, "华泰柏瑞")] == ["011452"]
    assert [record.fund_code for record in match_records(INDEX, "质量成长")] == ["011452"]
    assert [record.fund_code for record in match_records(INDEX, "证券")] == ["512888"]


def test_code_search_matches_substring() -> None:
    assert [record.fund_code for record in match_records(INDEX, "01145")] == ["011452"]
    assert [record.fund_code for record in match_records(INDEX, "512888")] == ["512888"]


def test_latin_names_match_case_insensitively() -> None:
    records = [FundExternalRecord(fund_code="000001", fund_name="ABC 混合")]
    assert match_records(records, "abc") == records
    assert match_records(records, "ABC") == records


def test_no_match_returns_empty() -> None:
    assert match_records(INDEX, "不存在的基金") == []
