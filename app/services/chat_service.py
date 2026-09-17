"""统一智能问答业务：RAG 检索 + Agent 工具调用，流式返回。

数据流：用户提问 → （有知识空间时）混合检索 → Agent 工具循环（Function Calling）
→ LLM 流式生成 → 落库对话记录。

自动路由：模型根据问题是否需要工具自行决定——需要计算/时间/检索等能力时调用
对应工具，否则直接流式回答。知识库相关片段作为前置检索上下文注入系统提示。
"""
from __future__ import annotations

import ast
import json
import logging
import operator
from datetime import datetime
from typing import Any, AsyncIterator

from sqlalchemy import func, select

from app.ai import build_embedder, build_llm
from app.db.database import SessionLocal
from app.models.chat import ChatSession, ChatMessage
from app.models.knowledge import Chunk, Document, KnowledgeSpace
from app.rag.reranker import build_reranker
from app.rag.retriever import Retriever
from app.services import config_service

logger = logging.getLogger(__name__)

_HISTORY_LIMIT = 10
_TITLE_MAX = 20
MAX_ITERATIONS = 6

# 追加到系统提示，让模型知晓可用的工具能力
_TOOL_HINT = (
    "\n\n你可以调用以下工具来完成任务：数学计算、当前时间查询、知识库语义搜索、"
    "知识空间统计、文件列表查询。当用户问题需要这些能力时，请调用对应工具，"
    "再用自然语言整合结果回答；若无需工具，直接简洁回答即可。"
)


# ---- 工具定义（OpenAI Function Calling 格式） ----
def _tool_defs() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "计算一个数学表达式的值，如 '2+3*4'",
                "parameters": {
                    "type": "object",
                    "properties": {"expression": {"type": "string", "description": "数学表达式"}},
                    "required": ["expression"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "current_time",
                "description": "获取当前日期和时间",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "semantic_search",
                "description": "在指定知识库中进行语义检索，返回相关文档片段",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索问题"},
                        "space_id": {"type": "string", "description": "知识空间 ID（可选）"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "space_stats",
                "description": "查询某个知识空间的文件数量与切片数量统计",
                "parameters": {
                    "type": "object",
                    "properties": {"space_id": {"type": "string", "description": "知识空间 ID（可选）"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "file_list",
                "description": "列出某个知识空间的文件列表",
                "parameters": {
                    "type": "object",
                    "properties": {"space_id": {"type": "string", "description": "知识空间 ID（可选）"}},
                },
            },
        },
    ]


# ---- 安全数学计算 ----
_SAFE_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_SAFE_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINOPS:
        return _SAFE_BINOPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNARY:
        return _SAFE_UNARY[type(node.op)](_eval_node(node.operand))
    raise ValueError("不支持的表达式")


def _calculator(expression: str) -> str:
    try:
        value = _eval_node(ast.parse(expression.strip(), mode="eval").body)
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value)
    except Exception as exc:  # noqa: BLE001
        return f"计算错误：{exc}"


def _current_time() -> str:
    now = datetime.now()
    weekdays = "一二三四五六日"
    return f"{now.strftime('%Y-%m-%d %H:%M:%S')} 星期{weekdays[now.weekday()]}"


async def _resolve_space(db, user_id: str, space_id: str | None) -> KnowledgeSpace | None:
    if not space_id:
        return None
    result = await db.execute(
        select(KnowledgeSpace).where(
            KnowledgeSpace.id == space_id, KnowledgeSpace.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def _semantic_search(db, embedder, query: str, space_id: str | None, user_id: str) -> str:
    if not query:
        return "缺少检索问题"
    if not space_id:
        return "未指定知识空间，请在问题中说明或选择知识库"
    space = await _resolve_space(db, user_id, space_id)
    if space is None:
        return "知识空间不存在或无权访问"
    cfg = await config_service.get_runtime(db)
    retriever = Retriever(
        embedder,
        reranker=build_reranker(cfg),
        rrf_k=config_service.get_int(cfg, "rrf_k", 60),
    )
    top_k = config_service.get_int(cfg, "top_k", 3)
    chunks = await retriever.retrieve(
        db, query, space_id, "hybrid", top_k, 0.0,
        rerank_top_m=config_service.get_int(cfg, "rerank_top_m", top_k * 3),
    )
    if not chunks:
        return "未检索到相关内容"
    return json.dumps([{"片段": c["content"][:300]} for c in chunks], ensure_ascii=False)


async def _space_stats(db, space_id: str | None, user_id: str) -> str:
    space = await _resolve_space(db, user_id, space_id)
    if space is None:
        return "未指定或无法访问该知识空间"
    doc_count = (
        await db.execute(select(func.count()).select_from(Document).where(Document.space_id == space_id))
    ).scalar_one()
    chunk_count = (
        await db.execute(select(func.count()).select_from(Chunk).where(Chunk.space_id == space_id))
    ).scalar_one()
    return json.dumps(
        {"空间名称": space.name, "文件数": doc_count, "切片数": chunk_count}, ensure_ascii=False
    )


async def _file_list(db, space_id: str | None, user_id: str) -> str:
    space = await _resolve_space(db, user_id, space_id)
    if space is None:
        return "未指定或无法访问该知识空间"
    rows = await db.execute(
        select(Document.filename, Document.status).where(Document.space_id == space_id)
    )
    files = [{"文件名": r[0], "状态": r[1]} for r in rows.all()]
    return json.dumps(files, ensure_ascii=False)


async def _execute_tool(
    db, embedder, name: str, args: dict, user_id: str, default_space_id: str | None
) -> str:
    space_id = args.get("space_id") or default_space_id
    if name == "calculator":
        return _calculator(str(args.get("expression", "")))
    if name == "current_time":
        return _current_time()
    if name == "semantic_search":
        return await _semantic_search(db, embedder, str(args.get("query", "")), space_id, user_id)
    if name == "space_stats":
        return await _space_stats(db, space_id, user_id)
    if name == "file_list":
        return await _file_list(db, space_id, user_id)
    return f"未知工具：{name}"


# ---- 会话与检索辅助 ----
async def _get_or_create_conversation(
    db, user_id: str, conversation_id: str | None, space_id: str | None, title: str | None
) -> ChatSession:
    if conversation_id:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == conversation_id, ChatSession.user_id == user_id
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            logger.warning("会话不存在: conversation_id=%s, user_id=%s", conversation_id, user_id)
            raise LookupError("会话不存在")
        if space_id:
            conversation.space_id = space_id
            await db.commit()
        logger.info("会话复用: conversation_id=%s, space_id=%s", conversation.id, conversation.space_id)
        return conversation

    conversation = ChatSession(
        user_id=user_id,
        space_id=space_id,
        title=title or "新会话",
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    logger.info(
        "会话创建: conversation_id=%s, user_id=%s, space_id=%s",
        conversation.id,
        user_id,
        space_id or "-",
    )
    return conversation


async def _load_history(db, conversation_id: str) -> list[dict]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.id.desc())
        .limit(_HISTORY_LIMIT)
    )
    rows = list(result.scalars().all())
    rows.reverse()
    history = [{"role": m.role, "content": m.content} for m in rows]
    logger.debug("历史消息加载: conversation_id=%s, 条数=%d", conversation_id, len(history))
    return history


async def _build_citations(db, chunks: list[dict]) -> list[dict]:
    doc_ids = {c.get("document_id") for c in chunks if c.get("document_id")}
    filenames: dict[str, str] = {}
    if doc_ids:
        rows = await db.execute(
            select(Document.id, Document.filename).where(Document.id.in_(doc_ids))
        )
        filenames = {r[0]: r[1] for r in rows.all()}
    return [
        {
            "chunk_id": c["chunk_id"],
            "document_id": c.get("document_id", ""),
            "filename": filenames.get(c.get("document_id", ""), ""),
            "content": c.get("content", "")[:200],
            "score": round(float(c.get("score", 0.0)), 4),
        }
        for c in chunks
    ]


def _build_rag_context(chunks: list[dict], max_chars: int) -> str:
    """将检索片段拼装为上下文，单片段截断并限制总长度，避免过长导致模型复述或截断。"""
    parts: list[str] = []
    total = 0
    for i, c in enumerate(chunks):
        text = str(c.get("content", ""))[:500].strip()
        if not text:
            continue
        if total + len(text) > max_chars:
            break
        parts.append(f"[{i + 1}] {text}")
        total += len(text)
    return "\n\n".join(parts)


async def _generate_title(llm, question: str) -> str:
    """生成会话标题：有供应商时用 LLM 生成，失败或无供应商时降级为切分用户输入。"""
    text = (question or "").strip()
    if not text:
        return "新会话"
    if llm is not None:
        try:
            resp = await llm.complete(
                [{"role": "user", "content": f"请用不超过10个字概括以下问题，只输出标题：{text}"}],
                temperature=0.0,
            )
            generated = (resp.get("content") or "").strip().strip('"').strip("'").strip()
            if generated:
                return generated[:_TITLE_MAX]
        except Exception:  # noqa: BLE001 - 标题生成失败即降级
            pass
    return text[:_TITLE_MAX]


# ---- 无供应商时的规则兜底（内置话术 + 检索抽取式回答） ----
_SELF_INTRO_KEYWORDS = (
    "自我介绍", "介绍你自己", "介绍一下你", "你是谁", "你能做什么", "你能干什么",
    "你会什么", "你的功能", "你有什么能力", "你会哪些",
)
_GREETING_KEYWORDS = (
    "你好", "您好", "hello", "嗨", "在吗", "在不在", "早上好", "中午好", "晚上好", "下午好",
)
_THANKS_KEYWORDS = ("谢谢", "感谢", "thank", "辛苦", "多谢")


def _fallback_answer(question: str, citations: list[dict]) -> str:
    """未配置大模型供应商时的兜底回答：
    1. 自我介绍 / 问候 / 感谢 → 内置话术；
    2. 知识库检索命中 → 抽取式返回原文片段；
    3. 未命中 → 提示先上传知识库。
    """
    q = (question or "").lower()
    if any(k in q for k in _SELF_INTRO_KEYWORDS):
        return (
            "你好，我是基于检索增强生成（RAG）技术的智能问答助手。"
            "我可以针对你上传到知识库的文档进行问答、检索与内容总结。"
            "你可以先在「知识库」中上传并处理文档，然后在会话里选择对应知识空间向我提问。"
        )
    if any(k in q for k in _GREETING_KEYWORDS):
        return "你好呀！我是你的智能问答助手，请在上传知识库并选择知识空间后向我提问。"
    if any(k in q for k in _THANKS_KEYWORDS):
        return "不客气，很高兴能帮到你！"

    if citations:
        lines = []
        for c in citations[:3]:
            lines.append(c.get("content", ""))
        return "\n".join(lines)

    return (
        "我在当前知识库中没有检索到相关内容。"
        "请先在「知识库」中上传相关文档并完成处理，再选择对应知识空间向我提问。"
    )


# ---- 统一问答流 ----
async def chat_stream(
    user_id: str,
    question: str,
    space_id: str | None,
    conversation_id: str | None,
    title: str | None,
) -> AsyncIterator[dict]:
    """统一智能问答流，产出事件：meta / citations / delta / error / done。"""
    logger.info(
        "Agent 请求: user_id=%s, space_id=%s, conversation_id=%s, question=%s",
        user_id,
        space_id or "-",
        conversation_id or "-",
        (question or "")[:50],
    )
    async with SessionLocal() as db:
        cfg = await config_service.get_runtime(db)

        embedder = build_embedder(cfg)
        try:
            llm = build_llm(cfg)
        except Exception as exc:  # noqa: BLE001 - 未配置供应商时降级（标题切分、无回答）
            logger.warning("大模型构建失败（未配置供应商），降级为无回答模式: %s", exc)
            llm = None

        try:
            conversation = await _get_or_create_conversation(
                db, user_id, conversation_id, space_id, title
            )
        except LookupError as exc:
            yield {"type": "error", "data": str(exc)}
            return

        history = await _load_history(db, conversation.id)

        # 前置 RAG 检索：选中知识空间时检索并注入上下文 + 产出引用来源
        citations: list[dict] = []
        context = ""
        if space_id:
            retriever = Retriever(
                embedder,
                reranker=build_reranker(cfg),
                rrf_k=config_service.get_int(cfg, "rrf_k", 60),
            )
            mode = str(cfg.get("retrieval_mode", "hybrid"))
            top_k = config_service.get_int(cfg, "top_k", 5)
            threshold = config_service.get_float(cfg, "similarity_threshold", 0.0)
            rerank_top_m = config_service.get_int(cfg, "rerank_top_m", top_k * 3)
            chunks = await retriever.retrieve(
                db, question, space_id, mode, top_k, threshold, rerank_top_m
            )
            citations = await _build_citations(db, chunks)
            context = _build_rag_context(
                chunks, config_service.get_int(cfg, "rag_context_max_chars", 3000)
            )
            logger.info(
                "RAG 前置检索: space_id=%s, mode=%s, 命中=%d, context 长度=%d",
                space_id,
                mode,
                len(chunks),
                len(context),
            )

        if context:
            system_content = str(cfg.get("prompt_rag", "")).format(
                context=context, question=question
            ) + _TOOL_HINT
        else:
            system_content = str(cfg.get("prompt_system", "")) + _TOOL_HINT

        # 落库用户消息
        db.add(ChatMessage(conversation_id=conversation.id, role="user", content=question))
        await db.commit()
        logger.info("消息保存成功: conversation_id=%s, role=user, len=%d", conversation.id, len(question))

        yield {"type": "meta", "data": {"conversation_id": conversation.id, "space_id": space_id}}
        yield {"type": "citations", "data": citations}

        messages: list[dict[str, Any]] = (
            [{"role": "system", "content": system_content}]
            + history
            + [{"role": "user", "content": question}]
        )

        full = ""
        if llm is None:
            logger.info("未配置大模型供应商，进入内置话术/检索兜底回答模式")
            full = _fallback_answer(question, citations)
            yield {"type": "delta", "data": full}
        else:
            max_tokens = config_service.get_int(cfg, "max_tokens", 2048)
            try:
                for _ in range(MAX_ITERATIONS):
                    round_text = ""
                    async for delta in llm.stream(messages, tools=_tool_defs(), max_tokens=max_tokens):
                        round_text += delta
                        full += delta
                        yield {"type": "delta", "data": delta}

                    tool_calls = llm.last_tool_calls
                    if not tool_calls:
                        break

                    # 将模型发起的工具调用（OpenAI 标准格式）追加进上下文
                    messages.append(
                        {
                            "role": "assistant",
                            "content": round_text or None,
                            "tool_calls": [
                                {
                                    "id": tc["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tc["name"],
                                        "arguments": tc.get("arguments", ""),
                                    },
                                }
                                for tc in tool_calls
                            ],
                        }
                    )
                    for tc in tool_calls:
                        name = tc["name"]
                        try:
                            args = json.loads(tc.get("arguments") or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        logger.info("工具调用: name=%s, args=%s", name, args)
                        result = await _execute_tool(db, embedder, name, args, user_id, space_id)
                        logger.debug("工具调用结果: name=%s, result=%s", name, result[:200])
                        messages.append(
                            {"role": "tool", "tool_call_id": tc.get("id", ""), "content": result}
                        )
                else:
                    full = "已达到最大工具调用次数，请稍后重试。"
                    yield {"type": "delta", "data": full}
            except Exception as exc:  # noqa: BLE001
                # 内部异常细节仅入日志，对外返回统一文案（不泄露 API 细节）
                logger.exception("智能问答生成失败: %s", exc)
                if not full:
                    full = "服务器内部错误，请稍后重试。"
                    yield {"type": "delta", "data": full}

        assistant_msg = ChatMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=full,
            citations=citations or None,
        )
        db.add(assistant_msg)
        if not conversation.title or conversation.title == "新会话":
            conversation.title = await _generate_title(llm, question)
            logger.info("会话标题生成: conversation_id=%s, title=%s", conversation.id, conversation.title)
        conversation.updated_at = datetime.now()
        await db.commit()
        logger.info(
            "消息保存成功: conversation_id=%s, role=assistant, len=%d",
            conversation.id,
            len(full),
        )

        yield {
            "type": "done",
            "data": {
                "conversation_id": conversation.id,
                "message_id": assistant_msg.id,
                "content": full,
            },
        }


# ===== 会话 CRUD =====
async def list_conversations(db, user_id: str) -> list[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_conversation(db, user_id: str, conversation_id: str) -> ChatSession | None:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == conversation_id, ChatSession.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def list_messages(db, user_id: str, conversation_id: str) -> list[ChatMessage] | None:
    conversation = await get_conversation(db, user_id, conversation_id)
    if conversation is None:
        return None
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.id)
    )
    return list(result.scalars().all())


async def delete_conversation(db, user_id: str, conversation_id: str) -> bool:
    conversation = await get_conversation(db, user_id, conversation_id)
    if conversation is None:
        return False
    await db.delete(conversation)
    await db.commit()
    return True