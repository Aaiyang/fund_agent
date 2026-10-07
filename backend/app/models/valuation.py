"""估值功能自己的输入数据.

估值需要两件公共主数据里没有的东西：基金公司写的「业绩比较基准」原话，以及
（将来）我们当时给出的估值快照用于回算准度。它们都放在本模块的表里，理由见
`FundBenchmark` 的 docstring。
"""

from datetime import datetime

from sqlmodel import Field

from app.models.base import BaseModel


class FundBenchmark(BaseModel, table=True):
    """一只基金的业绩比较基准原文（档案页那句话）.

    为什么不挂回 `fund`：`fund.benchmark` 曾经作为"从数据源抄来的一句展示文案"
    被删掉（迁移 `f6c9a3d1e2b8`），删的理由仍然成立——它不该出现在界面上。但估值
    必须读它：没有这句话就不知道该跟哪条指数、股票部分占多少权重。用途从"展示"
    变成"算法输入"之后，它归估值模块自己持有，不再回到公共主数据上，界面上也
    依然没有任何地方读它。

    也不建外键：基准是从档案页抄来的外部事实，允许早于我们给这只基金建主数据行
    而存在（穿透与基准法都可能在基金刚被搜到时就要用它）。
    """

    __tablename__ = "fund_benchmark"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    fund_code: str = Field(max_length=12, unique=True, index=True)
    # 原文最长见过 200 字左右（多段基准 + 括号说明），留足余量，不做截断：
    # 截断会把最后一段权重读丢，而读丢的结果是"估不出来"，很难归因到这里。
    text: str = Field(max_length=400)
    source: str = Field(default="akshare", max_length=50)
    fetched_at: datetime | None = Field(default=None)
