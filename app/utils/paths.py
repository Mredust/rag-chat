"""路径工具：项目根目录与存储相对路径之间的互转。

数据库中的文件路径（知识库文档、数据集、训练产出）统一保存为「项目根目录下的相对路径」
（如 ``data/uploads/xxx/file.docx``，不含盘符与前导分隔符）；需要访问文件时用
``to_abs_path`` 拼接项目根目录还原为绝对路径。
"""
from __future__ import annotations

from pathlib import Path

from app.core.config import BASE_DIR


def to_rel_path(path: str | Path) -> str:
    """将绝对路径转换为项目根目录下的相对路径（不含盘符与前导分隔符，正斜杠）。

    路径不在项目根目录下时原样返回（兼容已存在的绝对路径数据）。
    """
    p = Path(path)
    try:
        rel = p.resolve().relative_to(BASE_DIR.resolve())
    except (ValueError, OSError):
        return str(p)
    return str(rel).replace("\\", "/")


def to_abs_path(path: str | Path) -> Path:
    """将存储路径解析为绝对路径。

    已是绝对路径则直接返回；否则视为相对项目根目录的路径进行拼接。
    """
    s = str(path).replace("\\", "/").lstrip("/")
    if not s:
        return BASE_DIR
    p = Path(s)
    if p.is_absolute():
        return p.resolve()
    return (BASE_DIR / p).resolve()