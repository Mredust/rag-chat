"""Embedding 向量化封装（OpenAI 兼容接口 + 本地哈希降级）。

策略：
1. 若配置了 embedding_api_base / embedding_api_key，则优先走 OpenAI 兼容的
   Embedding API（支持任何兼容服务或本地推理框架）；
2. 否则回退为「哈希特征向量」——用 text 的字符/词 n-gram 散列到固定维度，
   保证向量维度统一、结果确定性，保证无外部 Embedding 服务时整条链路可跑通。

领域微调（Sentence-BERT 对比学习微调）属于 M3 算法优化阶段，接入方式：
将微调后的模型部署为 OpenAI 兼容接口后，配置 embedding_api_base 即可无缝切换。
"""
from __future__ import annotations

import gc
import hashlib
import json
import logging
import math
import shutil
import threading
from pathlib import Path
from typing import Iterable

from app.core.config import BASE_DIR, resolve_torch_device, settings

logger = logging.getLogger(__name__)

# 进程内本地向量模型缓存（避免每次请求重复加载模型）
_local_model_cache: dict[str, object] = {}
# 加载锁：并发请求同时触发加载时只允许一个线程真正加载，避免重复占用内存/CPU
_local_model_lock = threading.Lock()

# CPU 推理线程数（避免 PyTorch 抢占全部核心导致系统卡顿，按常见 4~8 核取值）
_CPU_THREADS = 4


def _resolve_local_model_path(model_name: str) -> Path | None:
    """在项目 models 目录（含 models/system 系统内置目录）下查找本地向量模型目录。"""
    base = BASE_DIR / "models"
    if not base.exists():
        return None
    candidates: list[Path] = []
    if model_name:
        candidates.append(base / model_name)
        candidates.append(base / "system" / model_name)
    candidates.append(base / "bge-large-zh-v1.5")
    candidates.append(base / "system" / "bge-large-zh-v1.5")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


# HuggingFace 模型结构配置的必要字段（用于区分模型配置与训练任务元数据）
_HF_CONFIG_KEYS = ("hidden_size", "num_hidden_layers", "vocab_size")


def _is_hf_config(data: object) -> bool:
    return isinstance(data, dict) and all(key in data for key in _HF_CONFIG_KEYS)


def ensure_hf_model_config(model_path: Path) -> None:
    """修复被训练任务元数据覆盖的 HuggingFace ``config.json``（微调产物目录）。

    训练任务曾把任务配置写进 ``config.json``，覆盖 SentenceTransformer 保存的模型结构配置，
    加载时会按 BERT-base 默认结构（768/12 层）建模，与微调权重形状不匹配而报
    ``ignore_mismatched_sizes`` 错误。检测到非模型结构配置时，先备份为
    ``train_task_config.json``，再按任务元数据里的基础模型恢复结构配置。
    """
    cfg_path = model_path / "config.json"
    data = None
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            data = None
        if _is_hf_config(data):
            return
        # 不是模型结构配置（训练任务元数据）：备份后重建
        backup = model_path / "train_task_config.json"
        try:
            shutil.copyfile(cfg_path, backup)
            cfg_path.unlink()
            logger.info("发现非模型结构的 config.json，已备份为 %s", backup)
        except OSError:
            pass

    # 从任务元数据（或备份）里取基础模型名，恢复基础模型的结构配置
    base_name = ""
    if isinstance(data, dict):
        base_name = str(data.get("base_model") or "")
    if not base_name:
        try:
            manifest = json.loads((model_path / "train_manifest.json").read_text(encoding="utf-8"))
            base_name = str(manifest.get("base_model") or "")
        except (OSError, ValueError, UnicodeDecodeError):
            base_name = ""

    if base_name:
        name = base_name.replace("\\", "/").strip("/")
        models_base = BASE_DIR / "models"
        for cand in (models_base / name, models_base / "system" / name, models_base / "ftm" / name):
            src = cand / "config.json"
            if not src.is_file() or src.resolve() == cfg_path.resolve():
                continue
            try:
                src_data = json.loads(src.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            if not _is_hf_config(src_data):
                continue
            try:
                shutil.copyfile(src, cfg_path)
                logger.info("已从基础模型 %s 恢复模型结构配置 config.json: %s", cand.name, model_path)
                return
            except OSError as exc:
                logger.warning("恢复 config.json 失败: %s (%s)", cfg_path, exc)
                return

    logger.warning(
        "模型目录 %s 缺少有效的 config.json，且未找到可用的基础模型配置，加载可能失败",
        model_path,
    )


def _load_local_model(model_path: Path):
    """加载并缓存本地 sentence-transformers 模型（线程安全，仅加载一次）。"""
    key = str(model_path)
    model = _local_model_cache.get(key)
    if model is not None:
        return model

    with _local_model_lock:
        # 双重检查：等待锁期间可能已被其他线程加载完成
        model = _local_model_cache.get(key)
        if model is not None:
            return model

        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(_CPU_THREADS)
        # 加载前修复可能被训练任务元数据覆盖的模型结构配置
        ensure_hf_model_config(model_path)
        logger.info("本地向量模型加载中: %s", model_path)
        model = SentenceTransformer(key, device=resolve_torch_device())
        _local_model_cache[key] = model

    dim = model.get_embedding_dimension()
    logger.info("本地向量模型就绪: %s (dim=%d)", model_path, dim)
    return model


def clear_local_model_cache() -> int:
    """释放进程内缓存的本地向量模型（返回释放数量），微调等大显存任务前调用。

    缓存的模型常驻显存，微调前清掉可腾出空间；下次向量化请求会自动重新加载。
    """
    import torch

    with _local_model_lock:
        count = len(_local_model_cache)
        _local_model_cache.clear()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    if count:
        logger.info("已释放 %d 个本地向量模型缓存（显存/内存已回收）", count)
    return count


class EmbeddingClient:
    """文本向量化客户端。"""

    def __init__(
        self,
        api_base: str = "",
        api_key: str = "",
        model: str = "",
        dim: int = 1024,
        local_path: Path | None = None,
    ) -> None:
        self.api_base = api_base
        self.api_key = api_key
        self.model = model
        self.dim = dim or 1024
        self.local_path = local_path
        self._local_model = None

    @property
    def use_remote(self) -> bool:
        return bool(self.api_base and self.api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """返回与输入一一对应的向量（维度 dim）。"""
        if not texts:
            return []
        if self.use_remote:
            logger.debug("Embedding 远程调用: model=%s, texts=%d", self.model or "-", len(texts))
            return self._embed_remote(texts)
        if self.local_path is not None:
            return self._embed_local(texts)
        return [self._hash_embedding(t, self.dim) for t in texts]

    # ---- OpenAI 兼容 Embedding API ----
    def _embed_remote(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI

        client = OpenAI(base_url=self.api_base, api_key=self.api_key)
        resp = client.embeddings.create(model=self.model, input=texts)
        vectors = [item.embedding for item in resp.data]
        return vectors

    # ---- 本地 sentence-transformers 向量（bge-large-zh-v1.5 等） ----
    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        if self._local_model is None:
            self._local_model = _load_local_model(self.local_path)  # type: ignore[arg-type]
            self.dim = self._local_model.get_embedding_dimension()  # type: ignore[attr-defined]
        vectors = self._local_model.encode(texts, normalize_embeddings=True)  # type: ignore[attr-defined]
        # 逐元素转为原生 Python float，避免 np.float32 被 Chroma 拒收
        return [[float(x) for x in v] for v in vectors]

    # ---- 本地哈希特征向量（降级） ----
    @staticmethod
    def _ngrams(text: str) -> Iterable[str]:
        lowered = (text or "").lower()
        words = lowered.split()
        yield from words
        # 字符二元组：兼顾中文等无空格语言，提升相邻文本的语义重叠
        compact = "".join(words)
        for i in range(len(compact) - 1):
            yield compact[i : i + 2]

    def _hash_embedding(self, text: str, dim: int) -> list[float]:
        vec = [0.0] * dim
        for gram in self._ngrams(text):
            digest = hashlib.md5(gram.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:8], "big") % dim
            sign = 1.0 if digest[8] & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


# 客户端缓存：同一配置只构建一次 EmbeddingClient（避免并发入库重复构建）
_embedder_cache: dict[str, EmbeddingClient] = {}
_embedder_lock = threading.Lock()


def build_embedder(cfg: dict[str, str]) -> EmbeddingClient:
    """由运行时配置构建 Embedding 客户端（按配置复用，避免重复构建）。"""
    try:
        dim = int(str(cfg.get("embedding_dim", "1024")).strip() or 1024)
    except ValueError:
        dim = 1024
    api_base = str(cfg.get("embedding_api_base", "")).strip()
    api_key = str(cfg.get("embedding_api_key", "")).strip()
    model = str(cfg.get("embedding_model", "")).strip()

    key = f"{api_base}|{api_key}|{model}|{dim}"
    with _embedder_lock:
        client = _embedder_cache.get(key)
        if client is not None:
            return client
        local_path = _resolve_local_model_path(model) if not (api_base and api_key) else None
        client = EmbeddingClient(
            api_base=api_base, api_key=api_key, model=model, dim=dim, local_path=local_path
        )
        _embedder_cache[key] = client

    mode = "remote" if client.use_remote else ("local" if client.local_path else "local-hash")
    logger.info(
        "向量模型准备：Embedding 客户端已构建 (model=%s, dim=%d, mode=%s)",
        model or "-",
        dim,
        mode,
    )
    return client