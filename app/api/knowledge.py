"""知识库路由：知识空间与文档的增删改查。"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import BusinessError, ErrorCode, success_response
from app.core.security import get_current_user_id
from app.db.database import get_db
from app.schemas.knowledge import (
    ChunkListResponse,
    ChunkResponse,
    DocumentCreate,
    DocumentListResponse,
    DocumentResponse,
    DocumentUpdate,
    KnowledgeSpaceCreate,
    KnowledgeSpaceListResponse,
    KnowledgeSpaceResponse,
    KnowledgeSpaceUpdate,
)
from app.services import knowledge_service
from app.services.ingest import chunk_by_strategy, save_upload, schedule_ingest
from app.services.parsing import parse_text

logger = logging.getLogger(__name__)

router = APIRouter()

# 导入向导支持的文件类型
IMPORT_ALLOWED_TYPES = {"pdf", "doc", "docx", "txt", "md"}


async def _get_owned_space(db: AsyncSession, user_id: str, space_id: str):
    space = await knowledge_service.get_space(db, user_id, space_id)
    if not space:
        raise BusinessError(ErrorCode.SPACE_NOT_FOUND, http_status=404)
    return space


def _build_import_config(
    segment_mode: str,
    parse_mode: str,
    max_level: int,
    keep_hierarchy: bool,
    chunk_size: int,
    chunk_overlap: int,
    separator: str,
    collapse_whitespace: bool,
    remove_urls_email: bool,
) -> dict:
    """将导入向导提交的表单参数归一为入库策略字典。"""
    config: dict = {
        "segment_mode": segment_mode,
        "parse_mode": parse_mode,
        "keep_hierarchy": keep_hierarchy,
    }
    if segment_mode == "hierarchy":
        config["max_level"] = max_level
    elif segment_mode == "custom":
        config["chunk_size"] = chunk_size
        config["chunk_overlap"] = chunk_overlap
        config["separator"] = separator
        config["collapse_whitespace"] = collapse_whitespace
        config["remove_urls_email"] = remove_urls_email
    else:
        # 自动分段与清洗：默认合并连续空白字符
        config["collapse_whitespace"] = True
    return config


def _parse_upload_content(file_type: str, content: bytes) -> str:
    """将上传文件写入临时文件后解析出纯文本，解析完成后清理临时文件。"""
    suffix = f".{file_type}" if file_type else ".txt"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
        return parse_text(file_type, tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# ===== 知识空间 =====


@router.post("/knowledge/spaces", summary="创建知识库")
async def create_space(
    data: KnowledgeSpaceCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    logger.info("创建知识库请求: name=%s", data.name)
    space = await knowledge_service.create_space(db, user_id, data)
    logger.info("知识库创建成功: space_id=%s, name=%s", space.id, space.name)
    return success_response(data=KnowledgeSpaceResponse.model_validate(space).model_dump(mode="json"))


@router.get("/knowledge/spaces", summary="知识库列表")
async def list_spaces(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    spaces = await knowledge_service.list_spaces(db, user_id)
    return success_response(
        data=KnowledgeSpaceListResponse(
            spaces=[KnowledgeSpaceResponse.model_validate(s) for s in spaces],
            total=len(spaces),
        ).model_dump(mode="json")
    )


@router.get("/knowledge/spaces/{space_id}", summary="知识库详情")
async def get_space(
    space_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    space = await _get_owned_space(db, user_id, space_id)
    return success_response(data=KnowledgeSpaceResponse.model_validate(space).model_dump(mode="json"))


@router.put("/knowledge/spaces/{space_id}", summary="更新知识库")
async def update_space(
    space_id: str,
    data: KnowledgeSpaceUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    space = await _get_owned_space(db, user_id, space_id)
    space = await knowledge_service.update_space(db, space, data)
    return success_response(data=KnowledgeSpaceResponse.model_validate(space).model_dump(mode="json"))


@router.delete("/knowledge/spaces/{space_id}", summary="删除知识库")
async def delete_space(
    space_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    space = await _get_owned_space(db, user_id, space_id)
    await knowledge_service.delete_space(db, space)
    return success_response(message="删除成功")


# ===== 文档 =====


@router.post("/knowledge/spaces/{space_id}/documents", summary="创建文档")
async def create_document(
    space_id: str,
    data: DocumentCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    space = await _get_owned_space(db, user_id, space_id)
    doc = await knowledge_service.create_document(db, space, data)
    return success_response(data=DocumentResponse.model_validate(doc).model_dump(mode="json"))


@router.get("/knowledge/spaces/{space_id}/documents", summary="文档列表")
async def list_documents(
    space_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_space(db, user_id, space_id)
    docs = await knowledge_service.list_documents(db, space_id)
    return success_response(
        data=DocumentListResponse(
            documents=[DocumentResponse.model_validate(d) for d in docs],
            total=len(docs),
        ).model_dump(mode="json")
    )


@router.get("/knowledge/spaces/{space_id}/documents/{doc_id}", summary="文档详情")
async def get_document(
    space_id: str,
    doc_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_space(db, user_id, space_id)
    doc = await knowledge_service.get_document(db, space_id, doc_id)
    if not doc:
        raise BusinessError(ErrorCode.DOCUMENT_NOT_FOUND, http_status=404)
    return success_response(data=DocumentResponse.model_validate(doc).model_dump(mode="json"))


@router.put("/knowledge/spaces/{space_id}/documents/{doc_id}", summary="更新文档")
async def update_document(
    space_id: str,
    doc_id: str,
    data: DocumentUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_space(db, user_id, space_id)
    doc = await knowledge_service.get_document(db, space_id, doc_id)
    if not doc:
        raise BusinessError(ErrorCode.DOCUMENT_NOT_FOUND, http_status=404)
    doc = await knowledge_service.update_document(db, doc, data)
    return success_response(data=DocumentResponse.model_validate(doc).model_dump(mode="json"))


@router.delete("/knowledge/spaces/{space_id}/documents/{doc_id}", summary="删除文档")
async def delete_document(
    space_id: str,
    doc_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_space(db, user_id, space_id)
    doc = await knowledge_service.get_document(db, space_id, doc_id)
    if not doc:
        raise BusinessError(ErrorCode.DOCUMENT_NOT_FOUND, http_status=404)
    await knowledge_service.delete_document(db, doc)
    return success_response(message="删除成功")


@router.post("/knowledge/spaces/{space_id}/upload", summary="上传文档（自动解析切片向量化）")
async def upload_document(
    space_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    space = await _get_owned_space(db, user_id, space_id)

    content = await file.read()
    if not content:
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="上传文件为空", http_status=400)

    filename = (file.filename or "unnamed.txt").strip()
    file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    if file_type not in {"pdf", "docx", "txt", "md", "json", "jsonl", "html", "xlsx", "csv"}:
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER,
            message="仅支持 pdf / docx / txt / md / json / jsonl / html / xlsx / csv 格式",
            http_status=400,
        )

    logger.info(
        "上传文档请求: space_id=%s, filename=%s, type=%s, size=%d",
        space_id,
        filename,
        file_type,
        len(content),
    )

    doc = await knowledge_service.create_document(
        db,
        space,
        DocumentCreate(
            filename=filename, file_type=file_type, file_size=len(content)
        ),
    )
    doc.storage_path = save_upload(space_id, doc.id, filename, content)
    await db.commit()
    await db.refresh(doc)

    # 后台执行解析→切片→向量化管线
    schedule_ingest(doc.id)
    logger.info("文档上传成功，已触发后台入库: doc_id=%s", doc.id)

    return success_response(data=DocumentResponse.model_validate(doc).model_dump(mode="json"))


@router.post("/knowledge/spaces/{space_id}/import/preview", summary="文档导入预览")
async def preview_document(
    space_id: str,
    file: UploadFile = File(...),
    segment_mode: str = Form("auto"),
    parse_mode: str = Form("fast"),
    max_level: int = Form(3),
    keep_hierarchy: bool = Form(False),
    chunk_size: int = Form(800),
    chunk_overlap: int = Form(10),
    separator: str = Form("\n"),
    collapse_whitespace: bool = Form(False),
    remove_urls_email: bool = Form(False),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_space(db, user_id, space_id)

    content = await file.read()
    if not content:
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="上传文件为空", http_status=400)
    filename = (file.filename or "unnamed.txt").strip()
    file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    if file_type not in IMPORT_ALLOWED_TYPES:
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER,
            message="仅支持 PDF / DOC / DOCX / TXT / MD 格式",
            http_status=400,
        )

    config = _build_import_config(
        segment_mode, parse_mode, max_level, keep_hierarchy,
        chunk_size, chunk_overlap, separator, collapse_whitespace, remove_urls_email,
    )
    text = await asyncio.to_thread(_parse_upload_content, file_type, content)
    chunks = chunk_by_strategy(text, config)

    return success_response(
        data={
            "filename": filename,
            "file_type": file_type,
            "file_size": len(content),
            "raw_text": text,
            "chunks": chunks,
            "chunk_count": len(chunks),
        }
    )


@router.post("/knowledge/spaces/{space_id}/import", summary="按策略批量导入文档")
async def import_documents(
    space_id: str,
    files: list[UploadFile] = File(...),
    segment_mode: str = Form("auto"),
    parse_mode: str = Form("fast"),
    max_level: int = Form(3),
    keep_hierarchy: bool = Form(False),
    chunk_size: int = Form(800),
    chunk_overlap: int = Form(10),
    separator: str = Form("\n"),
    collapse_whitespace: bool = Form(False),
    remove_urls_email: bool = Form(False),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    space = await _get_owned_space(db, user_id, space_id)

    strategy_config = _build_import_config(
        segment_mode, parse_mode, max_level, keep_hierarchy,
        chunk_size, chunk_overlap, separator, collapse_whitespace, remove_urls_email,
    )

    created: list = []
    for file in files:
        content = await file.read()
        if not content:
            continue
        filename = (file.filename or "unnamed.txt").strip()
        file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
        if file_type not in IMPORT_ALLOWED_TYPES:
            logger.warning("跳过不支持的文件类型: filename=%s, type=%s", filename, file_type)
            continue
        doc = await knowledge_service.create_document(
            db,
            space,
            DocumentCreate(filename=filename, file_type=file_type, file_size=len(content)),
        )
        doc.storage_path = save_upload(space_id, doc.id, filename, content)
        created.append(doc)

    await db.commit()
    for doc in created:
        await db.refresh(doc)

    for doc in created:
        schedule_ingest(doc.id, strategy_config)

    logger.info("批量导入完成: space_id=%s, documents=%d", space_id, len(created))
    return success_response(
        data={
            "documents": [DocumentResponse.model_validate(d).model_dump(mode="json") for d in created],
            "total": len(created),
        }
    )


@router.get(
    "/knowledge/spaces/{space_id}/documents/{doc_id}/chunks",
    summary="文档切片列表",
)
async def list_document_chunks(
    space_id: str,
    doc_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_space(db, user_id, space_id)
    doc = await knowledge_service.get_document(db, space_id, doc_id)
    if not doc:
        raise BusinessError(ErrorCode.DOCUMENT_NOT_FOUND, http_status=404)

    chunks = await knowledge_service.list_chunks(db, doc_id)
    return success_response(
        data=ChunkListResponse(
            chunks=[ChunkResponse.model_validate(c) for c in chunks],
            total=len(chunks),
        ).model_dump(mode="json")
    )