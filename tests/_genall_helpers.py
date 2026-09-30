"""通用「样例载荷」工厂：按 Pydantic 模型自动填充必填字段。

供「全 45 模板端到端冒烟测试」与「样例 docx 批量导出」共用，无需为每个模板硬编码载荷：
遍历 payload_model 的 model_fields，只对**必填**字段按类型合成合法值，其余走字段默认值。
尊重 min_length / max_length / ge / gt / le / lt / Literal / date / datetime / bool /
Decimal / Enum / list[BaseModel]（行表类只造 1 行，满足 min_length=1）。

设计取舍：列式引擎的 select 列对应 Pydantic 字段多为带默认值的 str / Literal，默认留空即可，
故仅填必填字段既能让所有模板通过 model_validate，又不会给 select 列塞入非法枚举值。
"""
from __future__ import annotations

import types
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

_SAMPLE_CN = "示例数据内容"


def _constraint(info: FieldInfo | None, key: str):
    """读取字段约束：先看 FieldInfo 直接属性，再扫描 Annotated metadata（pydantic v2 约束存放处）。"""
    if info is None:
        return None
    value = getattr(info, key, None)
    if value is not None:
        return value
    for meta in getattr(info, "metadata", []):
        value = getattr(meta, key, None)
        if value is not None:
            return value
    return None


def _unwrap_optional(annotation):
    """把 Optional[X] / X | None 还原为 X；非 Union 原样返回。"""
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        return args[0] if args else str
    return annotation


def _clamp_int(info: FieldInfo | None) -> int:
    v = 1
    ge, gt, le, lt = (_constraint(info, k) for k in ("ge", "gt", "le", "lt"))
    if ge is not None:
        v = max(v, int(ge))
    if gt is not None:
        v = max(v, int(gt) + 1)
    if le is not None:
        v = min(v, int(le))
    if lt is not None:
        v = min(v, int(lt) - 1)
    return v if v >= 1 else 1


def _sample_str(info: FieldInfo | None) -> str:
    minlen = _constraint(info, "min_length") or 1
    maxlen = _constraint(info, "max_length")
    text = _SAMPLE_CN
    if len(text) < minlen:
        text = text * (minlen // len(text) + 1)
    if maxlen and len(text) > maxlen:
        text = text[:maxlen]
    return text


def _build_model(model: type[BaseModel]) -> BaseModel:
    data = {}
    for name, info in model.model_fields.items():
        if not info.is_required():
            continue
        data[name] = _value_for(info.annotation, info)
    return model(**data)


def _value_for(annotation, info: FieldInfo | None = None):
    annotation = _unwrap_optional(annotation)
    origin = get_origin(annotation)

    if origin is Literal:
        return get_args(annotation)[0]

    if origin in (list, set, frozenset, tuple):
        args = get_args(annotation)
        elem = args[0] if args else str
        item = _value_for(elem, None)
        if origin is tuple:
            return [item]
        if origin is set:
            return {item}
        if origin is frozenset:
            return frozenset({item})
        return [item]

    if origin is dict:
        return {}

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _build_model(annotation)

    if annotation is date:
        return date.today()
    if annotation is datetime:
        return datetime.today()
    if annotation is time:
        return time(12, 0)
    if annotation is bool:
        return True
    if annotation is int:
        return _clamp_int(info)
    if annotation is float:
        return float(_clamp_int(info))
    if annotation is Decimal:
        return Decimal(str(_clamp_int(info)))
    if annotation is str:
        return _sample_str(info)

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return next(iter(annotation)).value

    return _sample_str(info)


def sample_payload(model_cls: type[BaseModel]) -> BaseModel:
    """构造一个仅填必填字段的合法模型实例。"""
    return _build_model(model_cls)


def sample_payload_dict(model_cls: type[BaseModel]) -> dict:
    """构造可提交 API 的样例载荷字典（date 等序列化为 JSON 友好值）。"""
    return _build_model(model_cls).model_dump(mode="json")


__all__ = ["sample_payload", "sample_payload_dict"]
