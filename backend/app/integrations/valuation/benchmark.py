"""业绩比较基准解析：把基金公司写的那句话读成「跟哪个指数、各占多少」.

基金公司不单独提供「跟踪指数」这个字段，只在招募说明书与档案页写一句
业绩比较基准，例如：

    沪深300指数收益率×95%＋银行活期存款利率（税后）×5%
    中证800指数收益率*60%+恒生指数收益率（使用估值汇率折算）*20%+上证国债指数收益率*20%

这句话里同时含我们需要的两件事：**跟哪个指数**、**股票部分占多大权重**。
本模块只负责把它拆成结构化片段，不做能不能取到价的判断（那是服务层的事），
也不做任何猜测：读不懂的段落一律标 `parseable=False`，让上层宁可不给估值。
"""

import re
from dataclasses import dataclass

# 全角运算符与括号统一成半角：同一份文本里两种写法都在流通。
_NORMALIZE = str.maketrans(
    {
        "×": "*",
        "ｘ": "*",
        "＋": "+",
        "，": ",",
        "（": "(",
        "）": ")",
        "％": "%",
        "　": "",
    }
)

# 现金/存款类段落：没有行情可取，加权计算时按 0 收益处理（见 analytics 里的说明）。
_CASH_TOKENS = ("活期存款", "银行存款", "定期存款", "同期存款", "利息收入", "货币市场", "储蓄存款")

# 出现即认为基准含境外资产：QDII 的净值按境外日历出，盘中给"预估"等于预测今晚
# 的收盘，口径上就是错的（他已定：QDII 不做实时预测）。商品与债券指数不在这里
# 判，它们只是我们行情目录里没有，交给上层按目录匹配自然落空。
_OVERSEAS_TOKENS = (
    "恒生",
    "港股",
    "H股",
    "中华港股",
    "纳斯达克",
    "标普",
    "道琼斯",
    "罗素",
    "日经",
    "东证",
    "富时",
    "德国",
    "法国",
    "英国",
    "美国",
    "中概",
    "全球",
    "亚太",
    "境外",
    "越南",
    "印度",
    "泰国",
)

# 文本里声明了汇率折算：说明该基准的收益已经含了人民币口径的汇率影响。
_FX_TOKENS = ("经汇率调整", "汇率折算", "使用估值汇率", "人民币计")

# 权重总是挂在段落末尾：`*95%`。
_WEIGHT = re.compile(r"[*]\s*(\d+(?:[.]\d+)?)\s*%")
# 指数段的固定写法是「<指数名>指数收益率」；其余表述（"标的指数"之类）认不出名字。
_INDEX = re.compile(r"^(.*?)指数收益率")
# 基准里指代"自己跟的那条指数"而不给名字的写法，加上前缀后仍然不是可查的指数名。
_GENERIC_INDEX_NAMES = frozenset({"标的", "该", "本", "对应", "相应", "相关", "同一", "目标"})


@dataclass(frozen=True)
class BenchmarkPart:
    """基准里的一段：一个指数和它的权重（百分点）."""

    index_name: str
    weight: float


@dataclass(frozen=True)
class BenchmarkPlan:
    """解析结果：`parts` 为空或 `parseable=False` 时不可用于估值."""

    parts: tuple[BenchmarkPart, ...] = ()
    cash_weight: float = 0.0
    overseas: bool = False
    fx_adjusted: bool = False
    parseable: bool = False

    @property
    def equity_weight(self) -> float:
        """指数段的合计权重（百分点），用来判断这只基金有多少资产能被行情解释."""
        return sum(part.weight for part in self.parts)


def parse_benchmark(text: str | None) -> BenchmarkPlan:
    """把业绩比较基准拆成指数段与现金段.

    只在结构完整可读时才给出片段：每段都要能认出「指数名 + 权重」，否则整条
    计划标为不可用。原因是估值的错法比错值更贵——把半懂的权重拿去加权，界面
    上会给出一个看着合理但来源可疑的数。
    """
    raw = (text or "").strip()
    if not raw:
        return BenchmarkPlan()

    normalized = raw.translate(_NORMALIZE)
    plan_overseas = any(token in normalized for token in _OVERSEAS_TOKENS)
    plan_fx = any(token in normalized for token in _FX_TOKENS)
    unusable = BenchmarkPlan(overseas=plan_overseas, fx_adjusted=plan_fx, parseable=False)

    names: list[str] = []
    weights: list[float | None] = []
    cash_weights: list[float] = []
    for segment in (piece.strip() for piece in normalized.split("+")):
        body = _WEIGHT.sub("", segment).strip()
        if not body:
            continue
        weight = _weight_of(segment)
        if any(token in body for token in _CASH_TOKENS):
            cash_weights.append(weight if weight is not None else 0.0)
            continue
        name = _index_name_of(body)
        if name is None:
            return unusable
        names.append(name)
        weights.append(weight)

    if not names:
        return unusable

    if any(weight is None for weight in weights):
        # 只有一条指数、没写权重，就是整条基准都跟着它（"中证500指数收益率"）。
        if len(names) == 1 and not cash_weights and weights[0] is None:
            parts = (BenchmarkPart(index_name=names[0], weight=100.0),)
        else:
            return unusable
    else:
        parts = tuple(
            BenchmarkPart(index_name=name, weight=weight)
            for name, weight in zip(names, weights, strict=True)
            if weight is not None
        )

    # 现金段 = 明写的存款部分 + 没分配到任何段的剩余权重。两者在估值里都按 0 收益
    # 处理，分开写会让"基准里 5% 存款"这件事在读结果时看不出来。
    accounted = sum(part.weight for part in parts) + sum(cash_weights)
    return BenchmarkPlan(
        parts=parts,
        cash_weight=sum(cash_weights) + max(0.0, 100.0 - accounted),
        overseas=plan_overseas,
        fx_adjusted=plan_fx,
        parseable=True,
    )


def _index_name_of(body: str) -> str | None:
    """从「经汇率调整的纳斯达克100指数收益率」里取出可用于查目录的指数名.

    前缀是修饰语而不是名字的一部分（"经汇率调整的"、"以人民币计"），按最后一个
    "的" 切；切完仍是"标的"这类占位说法时返回 None，让上层宁可不估。
    """
    match = _INDEX.match(body)
    if match is None:
        return None
    name = match.group(1).strip().rsplit("的", 1)[-1].strip()
    return name if name and name not in _GENERIC_INDEX_NAMES else None


def _weight_of(segment: str) -> float | None:
    """段落末尾的 `*NN%`；没有就返回 None（不猜权重）."""
    match = _WEIGHT.search(segment)
    return float(match.group(1)) if match else None
