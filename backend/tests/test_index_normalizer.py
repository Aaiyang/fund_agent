"""指数的行来自两个不同的 AKShare 接口，列名并不一样."""

from datetime import date

from app.integrations.fund_data.normalizer import normalize_index_rows


class TestNormalizeIndexRows:
    def test_accepts_lowercase_english_columns(self) -> None:
        rows = [{"date": date(2026, 9, 21), "close": 4500.5}, {"date": "2026-09-22", "close": "4544.588"}]
        quotes = normalize_index_rows(rows, "sh000300")
        assert [(quote.trade_date, quote.close) for quote in quotes] == [
            (date(2026, 9, 21), 4500.5),
            (date(2026, 9, 22), 4544.588),
        ]
        assert all(quote.index_code == "sh000300" for quote in quotes)

    def test_accepts_chinese_columns(self) -> None:
        quotes = normalize_index_rows([{"日期": "20260922", "收盘": "3399.93"}], "sz399006")
        assert [(quote.trade_date, quote.close) for quote in quotes] == [(date(2026, 9, 22), 3399.93)]

    def test_sorts_ascending_even_when_the_source_is_newest_last(self) -> None:
        rows = [{"date": "2026-09-22", "close": 1.0}, {"date": "2026-09-20", "close": 0.9}]
        assert [quote.trade_date for quote in normalize_index_rows(rows, "sh000001")] == [
            date(2026, 9, 20),
            date(2026, 9, 22),
        ]

    def test_drops_unusable_rows(self) -> None:
        rows = [
            {"date": "NaT", "close": 1.0},
            {"date": "2026-09-22", "close": "--"},
            {"date": "2026-09-22", "close": 0},
            {"date": "2026-09-22", "close": -1},
            {"close": 1.0},
        ]
        assert normalize_index_rows(rows, "sh000012") == []
