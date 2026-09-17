"""RAG 问答与会话路由（问答采用 SSE 流式返回）。"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import BusinessError, ErrorCode, success_response
from app.core.security import get_current_user_id
from app.db.database import get_db
from app.schemas.chat import (
    ChatRequest,
    ConversationListResponse,
    ConversationResponse,
    MessageListResponse,
    MessageResponse,
)
from app.services import chat_service, knowledge_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _sse(event: dict) -> str:
    """将事件字典编码为 SSE 数据帧。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/chat", summary="RAG 智能问答（SSE 流式）")
async def chat(
    req: ChatRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    # 预校验知识空间所有权
    if req.space_id:
        space = await knowledge_service.get_space(db, user_id, req.space_id)
        if not space:
            raise BusinessError(ErrorCode.SPACE_NOT_FOUND, http_status=404)

    async def event_stream():
        logger.info("SSE 连接建立: user_id=%s", user_id[:8])
        try:
            async for event in chat_service.chat_stream(
                user_id, req.question, req.space_id, req.conversation_id, req.title
            ):
                yield _sse(event)
        finally:
            logger.info("SSE 连接结束: user_id=%s", user_id[:8])

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/chat/conversations", summary="会话列表")
async def list_conversations(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    conversations = await chat_service.list_conversations(db, user_id)
    return success_response(
        data=ConversationListResponse(
            conversations=[ConversationResponse.model_validate(c) for c in conversations],
            total=len(conversations),
        ).model_dump(mode="json")
    )


@router.get("/chat/conversations/{conversation_id}/messages", summary="会话消息列表")
async def list_messages(
    conversation_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    messages = await chat_service.list_messages(db, user_id, conversation_id)
    if messages is None:
        raise BusinessError(ErrorCode.CONVERSATION_NOT_FOUND, http_status=404)
    return success_response(
        data=MessageListResponse(
            messages=[MessageResponse.model_validate(m) for m in messages],
            total=len(messages),
        ).model_dump(mode="json")
    )


@router.delete("/chat/conversations/{conversation_id}", summary="删除会话")
async def delete_conversation(
    conversation_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    ok = await chat_service.delete_conversation(db, user_id, conversation_id)
    if not ok:
        raise BusinessError(ErrorCode.CONVERSATION_NOT_FOUND, http_status=404)
    return success_response(message="删除成功")