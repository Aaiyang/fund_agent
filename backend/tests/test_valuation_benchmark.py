"""业绩比较基准解析：用真实档案里的原句当用例."""

from app.integrations.valuation.benchmark import parse_benchmark

# 以下三条是 005918 / 011452 / 012752 的档案原文（fund_individual_basic_info_xq）。
CSI300 = "沪深300指数收益率×95%＋银行活期存款利率（税后）×5%"
MULTI = "中证800指数收益率*60%+恒生指数收益率（使用估值汇率折算）*20%+上证国债指数收益率*20%"
NASDAQ = "经汇率调整的纳斯达克100指数收益率*95%+活期存款利率（税后）*5%"


def test_full_width_operators_still_parse() -> None:
    """基金公司写全角 `×＋（）`，也写半角 `*+()`，两种都得读得出来."""
    plan = parse_benchmark(CSI300)

    assert plan.parseable
    assert [(part.index_name, part.weight) for part in plan.parts] == [("沪深300", 95.0)]
    assert plan.cash_weight == 5.0
    assert not plan.overseas


def test_every_named_index_survives_with_its_own_weight() -> None:
    """多段基准要逐段解析：漏掉任何一段，加权结果就不是那条基准了."""
    plan = parse_benchmark(MULTI)

    assert plan.parseable
    assert [(part.index_name, part.weight) for part in plan.parts] == [
        ("中证800", 60.0),
        ("恒生", 20.0),
        ("上证国债", 20.0),
    ]
    assert plan.overseas and plan.fx_adjusted
    assert plan.equity_weight == 100.0


def test_an_overseas_benchmark_is_flagged_not_estimatable() -> None:
    """QDII 的净值按境外日历公布，盘中给数是在预测今晚收盘，口径上不能用."""
    plan = parse_benchmark(NASDAQ)

    assert plan.parseable
    assert [(part.index_name, part.weight) for part in plan.parts] == [("纳斯达克100", 95.0)]
    assert plan.overseas and plan.fx_adjusted


def test_a_lone_index_without_a_weight_means_the_whole_benchmark() -> None:
    plan = parse_benchmark("中证500指数收益率")

    assert plan.parseable
    assert [(part.index_name, part.weight) for part in plan.parts] == [("中证500", 100.0)]


def test_weight_left_unassigned_ends_up_in_the_cash_part() -> None:
    """基准只写了 80% 的指数时，剩下 20% 不能当成也会跟着动."""
    plan = parse_benchmark("沪深300指数收益率*60%+中债综合指数收益率*20%")

    assert plan.parseable
    assert plan.equity_weight == 80.0
    assert plan.cash_weight == 20.0


def test_missing_weights_on_several_parts_are_not_guessed() -> None:
    """两段都没写权重：任何拆分方式都是编造，整条计划作废."""
    assert not parse_benchmark("沪深300指数收益率+中债综合指数收益率").parseable


def test_an_unnamed_index_is_not_a_benchmark_we_can_use() -> None:
    """「标的指数收益率」没有给出指数名字，取不到行情，宁可不估."""
    assert not parse_benchmark("标的指数收益率×95%+银行活期存款利率（税后）×5%").parseable


def test_a_cash_only_benchmark_has_nothing_to_quote() -> None:
    assert not parse_benchmark("同期银行活期存款利率").parseable


def test_an_empty_benchmark_is_not_a_plan() -> None:
    for text in (None, "", "   "):
        plan = parse_benchmark(text)
        assert not plan.parseable
        assert plan.parts == ()
