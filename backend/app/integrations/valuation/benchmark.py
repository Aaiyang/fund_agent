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

# 基准文本里出现这些词，说明含 A 股以外的指数成分。**这个标记只用于说明基准构成，
# 不能用来否决整只基金**：A 股主动基金常带 10%~20% 的港股基准（实测 011452、
# 017489、022287 都是），它们的持仓照样能穿透估。真正"不能估"的判据是基金本身的
# 类型（QDII 的净值按境外日历公布），那由服务层按 fund_type 判。
# 基准里的境外指数最终会不会被用，取决于行情目录里有没有它——取不到价自然落空。
# 港股与 A 股在同一个交易时段（9:30–16:00，UTC+8）。"基准大头在港股"因此不构成
# 盘中估的否决理由——盘中估出来的就是今晚要用那次收盘，时间口径是同一个。
# 真正不能估的是跨时区市场：美股/欧股/日股在我们收盘之后才出数，盘中给数等于
# 预测另一个交易日，精度再高也是定义错。
_SAME_TIMEZONE_TOKENS = ("恒生", "港股", "H股", "中华港股", "红筹", "国企")
_CROSS_TIMEZONE_TOKENS = (
    "纳斯达克",
    "纳指",
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
_OVERSEAS_TOKENS = _SAME_TIMEZONE_TOKENS + _CROSS_TIMEZONE_TOKENS

# 文本里声明了汇率折算：说明该基准的收益已经含了人民币口径的汇率影响。
_FX_TOKENS = ("经汇率调整", "汇率折算", "使用估值汇率", "人民币计")

# 权重可以挂在段尾（`沪深300指数收益率*95%`），也可以挂在段首
# （`95%×恒生科技指数收益率`）：两种写法在档案里都真实存在，少认一种整条基准就
# 会被判为读不懂，而读不懂是不给估值，不是报错——错得很安静。
_TRAILING_WEIGHT = re.compile(r"[*]\s*(\d+(?:[.]\d+)?)\s*%\s*$")
_LEADING_WEIGHT = re.compile(r"^(\d+(?:[.]\d+)?)\s*%\s*[*]?\s*")
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
    has_offshore_index: bool = False
    fx_adjusted: bool = False
    parseable: bool = False

    @property
    def equity_weight(self) -> float:
        """指数段的合计权重（百分点），用来判断这只基金有多少资产能被行情解释."""
        return sum(part.weight for part in self.parts)

    @property
    def dominant_index_name(self) -> str | None:
        """权重最大的那条指数名，用来判这只基金跟着哪个市场结算."""
        if not self.parts:
            return None
        return max(self.parts, key=lambda part: part.weight).index_name

    @property
    def dominant_market(self) -> str:
        """大头指数所在的市场：`cross_tz`（跨时区）/ `hk`（港股）/ `cn`."""
        name = self.dominant_index_name
        if not name:
            return "cn"
        if any(token in name for token in _CROSS_TIMEZONE_TOKENS):
            return "cross_tz"
        if any(token in name for token in _SAME_TIMEZONE_TOKENS):
            return "hk"
        return "cn"

    @property
    def dominant_cross_timezone(self) -> bool:
        """净值跟着**跨时区**收盘出，因此不给盘中估.

        这是判"能不能盘中估"最可靠的信号：`fund.fund_type` 在多数行里是 NULL
        （库里 539001 建信纳斯达克100(QDII)A人民币 就没有类型），靠类型判会
        静默失效。而基准里"带一句恒生"不算——A 股主动基金常配 10%~20% 港股，
        它的主口径仍在 A 股。只有**占大头的那条指数**在跨时区市场，净值才是
        跟着另一个交易日的收盘出的。
        """
        return self.dominant_market == "cross_tz"


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
    offshore = any(token in normalized for token in _OVERSEAS_TOKENS)
    fx = any(token in normalized for token in _FX_TOKENS)
    unusable = BenchmarkPlan(has_offshore_index=offshore, fx_adjusted=fx, parseable=False)

    names: list[str] = []
    weights: list[float | None] = []
    cash_weights: list[float] = []
    for piece in normalized.split("+"):
        weight, body = _split_weight(piece)
        if not body:
            continue
        if any(token in body for token in _CASH_TOKENS):
            cash_weights.append(weight if weight is not None else 0.0)
            continue
        name = _index_name_of(body)
        if name is None:
            return unusable
        names.append(name)
        weights.append(weight)

    if not names:
        # 一段指数都没有（"一年期银行定期存款利率（税后）"这种纯存款基准）：
        # 没有任何行情能解释它的日内变化，只能走持仓穿透。
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
        has_offshore_index=offshore,
        fx_adjusted=fx,
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


def _split_weight(segment: str) -> tuple[float | None, str]:
    """把一段拆成（权重, 去掉权重后的正文）；没写权重返回 None，不猜.

    段尾与段首两种写法都认：`沪深300指数收益率*95%` 和 `95%×恒生科技指数收益率`
    在真实档案里都存在，只认一种会让后一种基准安静地变成"读不懂"。
    """
    text = segment.strip()
    if (tail := _TRAILING_WEIGHT.search(text)) is not None:
        return float(tail.group(1)), text[: tail.start()].strip()
    if (head := _LEADING_WEIGHT.match(text)) is not None:
        return float(head.group(1)), text[head.end() :].strip()
    return None, text
