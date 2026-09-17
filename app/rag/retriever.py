"""混合检索：向量检索（Chroma）+ 全文检索（MySQL FULLTEXT）+ RRF 融合。

- vector_search：语义召回，走 Chroma 向量库；
- fulltext_search：关键词召回，走 MySQL FULLTEXT 索引（含 LIKE 降级）；
- hybrid_search：RRF（Reciprocal Rank Fusion）融合两路候选；
- retrieve：统一入口，按模式（vector / fulltext / hybrid）返回 Top-K，再做重排序。
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
            logger.debug("向量检索召回: top_k=%d, 命中=%d", top_k, len(candidates))
        elif mode == "fulltext":
            candidates = await self.fulltext_search(db, question, space_id, top_k)
            logger.debug("全文检索召回: top_k=%d, 命中=%d", top_k, len(candidates))
        else:  # hybrid：两路召回 + RRF 融合
            vec = self.vector_search(question, space_id, top_k)
            ft = await self.fulltext_search(db, question, space_id, top_k)
            candidates = _rrf_merge(vec, ft, k=self.rrf_k)
            logger.debug("混合检索召回: 向量=%d, 全文=%d, 融合后=%d", len(vec), len(ft), len(candidates))

        # 相似度阈值过滤
        candidates = [c for c in candidates if c["score"] >= threshold]

        # 按分数降序
        candidates.sort(key=lambda x: x["score"], reverse=True)

        # 不重排序的策略（纯向量/纯全文/纯混合 RRF）直接取前 Top-K
        if not rerank:
            ranked = candidates[:top_k]
            logger.info("RAG 检索: mode=%s, top_k=%d, 命中=%d（无重排序）", mode, top_k, len(ranked))
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