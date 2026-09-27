"""混合检索：向量检索（Chroma）+ 全文检索（MySQL FULLTEXT）+ RRF 融合。

- vector_search：语义召回，走 Chroma 向量库；
- fulltext_search：关键词召回，走 MySQL FULLTEXT 索引（含 LIKE 降级）；
- hybrid_search：RRF（Reciprocal Rank Fusion）融合两路候选；
- retrieve：统一入口，按模式（vector / fulltext / hybrid）返回 Top-K，再做重排序；
- retrieve_layered：分层入口，① 向量库 → ② 数据库兜底 → ③ none（上层 LLM/内置兜底）。
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding import EmbeddingClient
from app.rag.chroma_store import get_collection
from app.rag.reranker import Reranker

logger = logging.getLogger(__name__)

# RRF 融合常数
_RRF_K = 60

# 检索结果统一结构
RetrievedChunk = dict  # {chunk_id, document_id, space_id, content, score, source}


def _rrf_merge(*ranked_lists: list[RetrievedChunk], k: int = _RRF_K) -> list[RetrievedChunk]:
    """多路召回结果按 chunk_id 融合，采用 RRF 打分。"""
    merged: dict[str, RetrievedChunk] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            cid = item["chunk_id"]
            rrf_score = 1.0 / (k + rank + 1)
            if cid not in merged:
                merged[cid] = dict(item)
                merged[cid]["score"] = 0.0
            merged[cid]["score"] += rrf_score
    return list(merged.values())


class Retriever:
    def __init__(
        self,
        embedder: EmbeddingClient,
        reranker: Reranker | None = None,
        rrf_k: int = _RRF_K,
    ) -> None:
        self.embedder = embedder
        self.reranker = reranker or Reranker()
        self.rrf_k = rrf_k

    # ---- 向量检索 ----
    def vector_search(self, question: str, space_id: str, top_k: int) -> list[RetrievedChunk]:
        vector = self.embedder.embed([question])[0]
        collection = get_collection()
        result = collection.query(
            query_embeddings=[vector],
            n_results=top_k,
            where={"space_id": space_id},
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        chunks: list[RetrievedChunk] = []
        for i, cid in enumerate(ids):
            dist = distances[i] if i < len(distances) else 0.0
            # L2 距离越小越相似，转化为 [0,1] 相似度
            score = 1.0 / (1.0 + float(dist))
            meta = metadatas[i] or {}
            chunks.append(
                {
                    "chunk_id": cid,
                    "document_id": meta.get("document_id", ""),
                    "space_id": space_id,
                    "content": documents[i] if i < len(documents) else "",
                    "score": score,
                    "source": "vector",
                }
            )
        return chunks

    # ---- 全文检索 ----
    async def fulltext_search(
        self, db: AsyncSession, question: str, space_id: str, top_k: int
    ) -> list[RetrievedChunk]:
        # 1) 优先 FULLTEXT
        fts = text(
            "SELECT c.id, c.document_id, c.space_id, c.content, "
            "MATCH(c.content) AGAINST (:q IN NATURAL LANGUAGE MODE) AS rel "
            "FROM chunk c "
            "WHERE c.space_id = :space_id "
            "AND MATCH(c.content) AGAINST (:q IN NATURAL LANGUAGE MODE) "
            f"ORDER BY rel DESC LIMIT {int(top_k)}"
        )
        try:
            rows = (await db.execute(fts, {"q": question, "space_id": space_id})).mappings().all()
        except Exception:
            rows = []
        if not rows:
            rows = await self._like_search(db, question, space_id, top_k)

        chunks: list[RetrievedChunk] = []
        for r in rows:
            chunks.append(
                {
                    "chunk_id": r["id"],
                    "document_id": r["document_id"],
                    "space_id": r["space_id"],
                    "content": r["content"],
                    "score": float(r.get("rel") or 1.0),
                    "source": "fulltext",
                }
            )
        return chunks

    async def _like_search(
        self, db: AsyncSession, question: str, space_id: str, top_k: int
    ) -> list:
        """FULLTEXT 失败（如中文未启用 ngram 分词）时的 LIKE 关键词降级。"""
        terms = [t for t in re.split(r"\s+", question.strip()) if t]
        if not terms:
            terms = [question]
        clauses = " OR ".join([f"c.content LIKE :t{i}" for i in range(len(terms))])
        sql = text(
            f"SELECT c.id, c.document_id, c.space_id, c.content, 1.0 AS rel "
            f"FROM chunk c WHERE c.space_id = :space_id AND ({clauses}) LIMIT {int(top_k)}"
        )
        params = {"space_id": space_id}
        for i, term in enumerate(terms):
            params[f"t{i}"] = f"%{term}%"
        rows = (await db.execute(sql, params)).mappings().all()
        return list(rows)

    # ---- 排序与重排 ----
    def _rank(
        self,
        question: str,
        mode: str,
        candidates: list[RetrievedChunk],
        top_k: int,
        rerank_top_m: int | None,
        rerank: bool,
    ) -> list[RetrievedChunk]:
        # 按分数降序
        candidates.sort(key=lambda x: x["score"], reverse=True)

        # 不重排序的策略（纯向量/纯全文/纯混合 RRF）直接取前 Top-K
        if not rerank:
            ranked = candidates[:top_k]
            logger.info(
                "RAG 检索: mode=%s, top_k=%d, 命中=%d（无重排序）", mode, top_k, len(ranked)
            )
            return ranked

        # 取候选集交给重排序器精排
        m = rerank_top_m if rerank_top_m is not None else max(top_k, 1) * 3
        ranked = self.reranker.rerank(question, candidates[: max(m, 1)], top_k=top_k)
        logger.info(
            "RAG 检索: mode=%s, top_k=%d, 候选=%d, 精排后=%d",
            mode,
            top_k,
            len(candidates[: max(m, 1)]),
            len(ranked),
        )
        return ranked

    # ---- 统一入口 ----
    async def retrieve(
        self,
        db: AsyncSession,
        question: str,
        space_id: str,
        mode: str = "hybrid",
        top_k: int = 5,
        threshold: float = 0.0,
        rerank_top_m: int | None = None,
        rerank: bool = True,
    ) -> list[RetrievedChunk]:
        if mode == "vector":
            candidates = self.vector_search(question, space_id, top_k)
            # 相似度阈值作用于向量相似度分数（1/(1+L2)，归一化向量下≈余弦语义）
            candidates = [c for c in candidates if c["score"] >= threshold]
            logger.debug("向量检索召回: top_k=%d, 命中=%d", top_k, len(candidates))
        elif mode == "fulltext":
            # 全文命中按关键词相关性排序，不适用相似度阈值（阈值语义是向量相似度）
            candidates = await self.fulltext_search(db, question, space_id, top_k)
            logger.debug("全文检索召回: top_k=%d, 命中=%d", top_k, len(candidates))
        else:  # hybrid：两路召回（向量先按阈值过滤）+ RRF 融合
            vec = self.vector_search(question, space_id, top_k)
            vec = [c for c in vec if c["score"] >= threshold]
            ft = await self.fulltext_search(db, question, space_id, top_k)
            candidates = _rrf_merge(vec, ft, k=self.rrf_k)
            logger.debug(
                "混合检索召回: 向量=%d(阈值过滤后), 全文=%d, 融合后=%d",
                len(vec), len(ft), len(candidates),
            )
        return self._rank(question, mode, candidates, top_k, rerank_top_m, rerank)

    # ---- 分层检索：① 向量库 → ② 数据库兜底 ----
    async def retrieve_layered(
        self,
        db: AsyncSession,
        question: str,
        space_id: str,
        mode: str = "hybrid",
        top_k: int = 5,
        threshold: float = 0.0,
        rerank_top_m: int | None = None,
        rerank: bool = True,
    ) -> tuple[list[RetrievedChunk], str]:
        """按约定的分层检索策略返回 (结果, 层级)。

        层级：
        - "vector"：第一层向量库（Chroma）命中，直接返回检索结果；
        - "db"：向量库无命中/不可用，第二层数据库（MySQL 全文/LIKE）兜底命中，
          返回结果并由调用方异步补齐向量（读写一致，幂等 upsert）；
        - "none"：两层皆空，交由上层决定 LLM 兜底或系统内置回答。
        向量库异常（索引损坏、目录漂移）按「向量库不存在」降级，不阻断检索。
        """
        # ---- 第一层：向量库 ----
        vector_raw: list[RetrievedChunk] = []
        if mode in ("vector", "hybrid"):
            try:
                vector_raw = self.vector_search(question, space_id, top_k)
            except Exception as exc:  # noqa: BLE001 - 向量库不可用时降级到数据库层
                logger.error("向量库检索异常（降级到数据库层）: %s", exc)

        if mode == "fulltext":
            db_hits = await self.fulltext_search(db, question, space_id, top_k)
            if db_hits:
                return self._rank(question, mode, db_hits, top_k, rerank_top_m, rerank), "db"
            logger.info("分层检索: mode=%s, 层级=none（数据库无命中）", mode)
            return [], "none"

        vec_ok = [c for c in vector_raw if c["score"] >= threshold]
        if mode == "vector":
            if vec_ok:
                return (
                    self._rank(question, mode, vec_ok, top_k, rerank_top_m, rerank),
                    "vector",
                )
        else:  # hybrid（含未知模式）：向量 + 全文 RRF 融合
            ft = await self.fulltext_search(db, question, space_id, top_k)
            merged = _rrf_merge(vec_ok, ft, k=self.rrf_k)
            if merged:
                layer = "vector" if vector_raw else "db"
                return self._rank(question, mode, merged, top_k, rerank_top_m, rerank), layer

        # ---- 第二层：数据库兜底（向量库无命中时查询 MySQL） ----
        if mode == "vector":
            db_hits = await self.fulltext_search(db, question, space_id, top_k)
            if db_hits:
                logger.info(
                    "分层检索: 向量库未命中，数据库兜底命中=%d, space_id=%s",
                    len(db_hits), space_id,
                )
                return (
                    self._rank(question, mode, db_hits, top_k, rerank_top_m, rerank),
                    "db",
                )

        logger.info(
            "分层检索: mode=%s, 向量库=%d, 层级=none（交由上层 LLM/内置兜底）",
            mode, len(vector_raw),
        )
        return [], "none"