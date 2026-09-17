"""提示词模板加载工具：从项目根目录 prompts/ 读取 .txt 模板。

命名约定：prompt_name 对应 prompts/<prompt_name>.txt，如 dataset_generate。
模板支持 {key} 占位符，通过 format_prompt 安全替换（仅替换已知键，内容中的花括号不受影响）。
"""
from __future__ import annotations

from pathlib import Path

from app.core.config import BASE_DIR

PROMPTS_DIR: Path = BASE_DIR / "prompts"

_prompt_cache: dict[str, str] = {}


def load_prompt(prompt_name: str) -> str:
    """加载指定名称的提示词模板，带进程内缓存。"""
    if prompt_name in _prompt_cache:
        return _prompt_cache[prompt_name]

    filepath = PROMPTS_DIR / f"{prompt_name}.txt"
    if not filepath.exists():
        raise FileNotFoundError(f"提示词文件不存在: {filepath}")

    content = filepath.read_text(encoding="utf-8")
    _prompt_cache[prompt_name] = content
    return content


def format_prompt(prompt_name: str, **kwargs) -> str:
    """加载模板并替换 {key} 占位符变量（不依赖 str.format，避免内容花括号干扰）。"""
    template = load_prompt(prompt_name)
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", str(value))
    return template


def clear_prompt_cache() -> None:
    """清空提示词缓存（开发调试时使用）。"""
    _prompt_cache.clear()