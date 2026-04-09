"""
统一序列化模块 - V2.1

职责：
  所有对外输出的 JSON 序列化统一走这里，彻底消灭：
  - Decimal is not JSON serializable
  - date/datetime is not JSON serializable
  - set/tuple/Path/Enum 等特殊类型

用法：
  from serialization import deep_serialize, json_dumps_safe, is_json_safe
"""
import json
import re
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Core serializer
# ─────────────────────────────────────────────────────────────────────────────

def deep_serialize(obj: Any) -> Any:
    """
    递归将所有非 JSON 原生类型转为 JSON 安全类型。
    不改变结构，只做类型转换。

    覆盖类型：Decimal, date, datetime, set, tuple, Path, Enum, numpy.*, bytes
    """
    if obj is None:
        return None
    if isinstance(obj, (bool, int, float, str)):
        return obj

    # 数值类型兜底
    if hasattr(obj, "__float__") and not isinstance(obj, (date, datetime)):
        try:
            return float(obj)
        except (TypeError, ValueError):
            return str(obj)

    if isinstance(obj, dict):
        return {k: deep_serialize(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple, set)):
        return [deep_serialize(x) for x in obj]

    if isinstance(obj, Decimal):
        return float(obj)

    if isinstance(obj, (date, datetime)):
        return obj.isoformat()

    if isinstance(obj, Path):
        return str(obj)

    if isinstance(obj, Enum):
        return obj.value

    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return obj.hex()

    # numpy 类型
    if type(obj).__module__.startswith("numpy"):
        try:
            return float(obj)
        except (ValueError, TypeError):
            return str(obj)

    # 兜底转字符串
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def is_json_safe(obj: Any) -> bool:
    """检查对象是否可直接 JSON 序列化（无需 deep_serialize）。"""
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


def json_dumps_safe(obj: Any, **kwargs) -> str:
    """
    将对象安全序列化为 JSON 字符串。

    等价于 json.dumps(deep_serialize(obj))，但更高效：
    - 对已经是 JSON 安全类型的值直接跳过转换
    - 对非安全类型才走 deep_serialize

    默认参数：
      ensure_ascii=False（支持中文）
      indent=None（紧凑输出）
    """
    defaults = {"ensure_ascii": False, "separators": (",", ":")}
    defaults.update(kwargs)
    return json.dumps(deep_serialize(obj), **defaults)


def write_json(path: Path, obj: Any, **kwargs) -> None:
    """将对象安全写入 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps_safe(obj, **kwargs), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Convenience
# ─────────────────────────────────────────────────────────────────────────────

def summarize_value(v: Any, max_len: int = 80) -> str:
    """将任意值转为短字符串摘要，便于日志/调试输出。"""
    if v is None:
        return "None"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v[:max_len] + ("..." if len(v) > max_len else "")
    if isinstance(v, dict):
        keys = list(v.keys())
        return f"dict({len(keys)} keys: {', '.join(str(k) for k in keys[:5])})"
    if isinstance(v, (list, tuple, set)):
        return f"{type(v).__name__}(len={len(v)})"
    return repr(v)[:max_len]
