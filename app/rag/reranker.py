"""重排序：对「问题-文档片段」候选集精细化打分。

架构上采用「两阶段检索」：先轻量召回 Top-N 缩小候选集（retriever），再精细重排序。
默认实现由 `build_reranker` 按运行时配置选择：配置了交叉编码器模型（如 bge-reranker）
时使用「问题-片段」联合编码打分；依赖缺失或模型加载失败时回退为
「词法重叠 + 检索分」的轻量代理精排（无外部依赖、可离线运行），保证检索链路不中断。
"""
from __future__ import annotations

import logging
from typing import Callable

from app.utils.paths import to_abs_path

RetrievedChunk = dict

logger = logging.getLogger(__name__)


def _ngrams(text: str) -> set[str]:
    lowered = (text or "").lower()
    words = lowered.split()
    grams = set(words)
    compact = "".join(words)
    for i in range(max(len(compact) - 1, 0)):
        grams.add(compact[i : i + 2])
    return grams


def lexical_score(query: str, content: str) -> float:
    """词法重叠度（Jaccard 变体），作为交叉编码的轻量代理。"""
    q = _ngrams(query)
    c = _ngrams(content)
    if not q or not c:
        return 0.0
    inter = q & c
    return len(inter) / (len(q) + len(c) - len(inter) + 1e-6)


class Reranker:
    def __init__(
        self,
        score_fn: Callable[[str, list[RetrievedChunk]], list[RetrievedChunk]] | None = None,
    ) -> None:
        # 自定义打分函数（可注入真实交叉编码器）
        self._score_fn = score_fn

    def rerank(
        self, query: str, candidates: list[RetrievedChunk], top_k: int | None = None
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []

        if self._score_fn is not None:
            ranked = self._score_fn(query, candidates)
        else:
            for item in candidates:
                overlap = lexical_score(query, item.get("content", ""))
                item["score"] = 0.5 * float(item.get("score", 0.0)) + 0.5 * overlap
            ranked = sorted(candidates, key=lambda x: x["score"], reverse=True)

        if top_k is not None:
            ranked = ranked[:top_k]
        return ranked


class CrossEncoderReranker:
    """交叉编码器重排序（如 bge-reranker），对「问题-片段」对联合编码打分。

    惰性加载 sentence-transformers 的 CrossEncoder；依赖未安装或模型加载失败时，
    `build_reranker` 会捕获异常并回退到词法代理重排。
    """

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder  # noqa: PLC0415 - 惰性加载

        self._model = CrossEncoder(model_name)

    def __call__(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        pairs = [(query, item.get("content", "")) for item in candidates]
        scores = self._model.predict(pairs)
        for item, score in zip(candidates, scores):
            item["score"] = float(score)
        return sorted(candidates, key=lambda x: x["score"], reverse=True)


# 已成功加载的交叉编码器按模型路径缓存，避免每次问答重复加载大模型
_RERANKER_CACHE: dict[str, Reranker] = {}


def build_reranker(cfg: dict[str, str]) -> Reranker:
    """按运行时配置构建重排序器。

    - `rerank_enabled` 且 `rerank_model` 已配置时，注入交叉编码器打分；
    - 依赖缺失 / 加载失败时回退为词法代理重排（不阻断检索链路）；
    - 加载成功的交叉编码器按模型路径缓存复用。
    """
    enabled = str(cfg.get("rerank_enabled", "")).strip().lower() in {"1", "true", "yes", "on"}
    model = str(cfg.get("rerank_model", "")).strip()
    if enabled and model:
        # 相对路径基于项目根目录拼接（如 rerankers/bge-reranker-base）
        model_path = str(to_abs_path(model))
        cached = _RERANKER_CACHE.get(model_path)
        if cached is not None:
            return cached
        try:
            logger.info("重排序模型准备：加载交叉编码器 %s", model_path)
            reranker = Reranker(score_fn=CrossEncoderReranker(model_path))
        except Exception as exc:  # noqa: BLE001 - 交叉编码器不可用则回退
            logger.warning("交叉编码器加载失败，回退词法代理重排: %s", exc)
        else:
            _RERANKER_CACHE[model_path] = reranker
            return reranker
    return Reranker()