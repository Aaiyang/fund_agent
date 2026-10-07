"""评测结果的 schema."""

from pydantic import (
    BaseModel,
    Field,
)


class ScoreSchema(BaseModel):
    """评分模型返回的单指标打分结构（分数 + 理由）."""

    score: float = Field(description="provide a score between 0 and 1")
    reasoning: str = Field(description="provide a one sentence reasoning")
