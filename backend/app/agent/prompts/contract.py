"""把 pydantic schema 翻译成给模型看的输出契约文本.

单一来源：字段名、枚举取值、必填与否、长度与数值上限只在 schema 里写一次，提示词读它
而不是再抄一遍中文。两处各写一遍的后果是实测到的两类故障：提示词说"每条发现不超过
120字"而 schema 允许 700；``ReviewIssue.role`` 是必填英文枚举，提示词只给了中文角色名，
模型漏字段 → pydantic ValidationError → 整个交叉审核被判未完成。
"""

import types
from typing import Annotated, Literal, Union, get_args, get_origin

from annotated_types import Ge, Gt, Le, Lt, MaxLen, MinLen
from pydantic import BaseModel

from app.schemas.multi_role_research import AgentAnalysis, ResearchReview

_MAX_DEPTH = 3


def _constraint_text(constraints: tuple[object, ...]) -> list[str]:
    """把 annotated_types 的约束写成短语；不认识的一律忽略."""
    notes: list[str] = []
    for constraint in constraints:
        if isinstance(constraint, MaxLen):
            notes.append(f"最多 {int(constraint.max_length)}")
        elif isinstance(constraint, MinLen):
            notes.append(f"至少 {int(constraint.min_length)}")
        elif isinstance(constraint, Ge):
            notes.append(f">= {constraint.ge}")
        elif isinstance(constraint, Gt):
            notes.append(f"> {constraint.gt}")
        elif isinstance(constraint, Le):
            notes.append(f"<= {constraint.le}")
        elif isinstance(constraint, Lt):
            notes.append(f"< {constraint.lt}")
        else:
            # 正则约束由 pydantic 以通用元数据携带（如六位基金代码），不在 annotated_types 里。
            pattern = getattr(constraint, "pattern", None)
            if pattern:
                notes.append(f"格式 {pattern}")
    return notes


def _describe(annotation: object, depth: int) -> str:
    """一个类型（含其 Annotated 约束）的契约描述."""
    origin = get_origin(annotation)
    if origin is Annotated:
        base, *constraints = get_args(annotation)
        parts = [_describe(base, depth)] + _constraint_text(tuple(constraints))
        return "，".join(part for part in parts if part)
    if origin is Literal:
        return "只能是 " + " | ".join(str(value) for value in get_args(annotation))
    if origin is Union or origin is types.UnionType:
        # `X | None` 写出来的是 types.UnionType 而不是 typing.Union，两个都要认：
        # 只认后者时嵌套模型不展开，契约里只剩一行类型名，模型根本不知道要填什么字段。
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        joined = " 或 ".join(_describe(member, depth) for member in members)
        return joined + ("，可为 null" if len(members) != len(get_args(annotation)) else "")
    if origin in (list, set, tuple) or annotation in (list, set, tuple):
        args = get_args(annotation)
        if args and isinstance(args[-1], type) and args[-1] is Ellipsis:
            args = args[:-1]
        item = _describe(args[0], depth + 1) if args else "任意"
        return f"数组，每项: {item}" if depth < _MAX_DEPTH else "数组"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _describe_model(annotation, depth + 1) if depth < _MAX_DEPTH else annotation.__name__
    if annotation is types.NoneType:  # pragma: no cover - defensive
        return "null"
    return getattr(annotation, "__name__", str(annotation))


def _describe_model(model: type[BaseModel], depth: int) -> str:
    """字段清单：名称（必填与否、类型与约束）.

    超过 ``_MAX_DEPTH`` 层不再展开，只给类型名——契约文本也要有界。
    """
    pad = "  " * (depth + 1)
    lines = []
    for name, field in model.model_fields.items():
        # Field(max_length=...) 这类字段级约束落在 field.metadata，不在 annotation 上。
        marks = [
            "必填" if field.is_required() else "可省略",
            _describe(field.annotation, depth),
            *_constraint_text(tuple(field.metadata)),
        ]
        lines.append(f"{pad}- {name}（{'，'.join(mark for mark in marks if mark)}）")
    return "\n" + "\n".join(lines)


def describe_schema(model: type[BaseModel]) -> str:
    """返回可直接拼进提示词的契约段落.

    Raises:
        ValueError: schema 没有任何字段，说明传错了对象。
    """
    if not model.model_fields:
        raise ValueError("schema has no fields to describe")
    return f"输出结构（字段名与取值逐字照此，不能增删字段）:{_describe_model(model, 0)}"


AGENT_ANALYSIS_CONTRACT = describe_schema(AgentAnalysis)
RESEARCH_REVIEW_CONTRACT = describe_schema(ResearchReview)
