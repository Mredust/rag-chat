"""知识库相关 Schema。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeSpaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=5000)


class KnowledgeSpaceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=5000)


class KnowledgeSpaceResponse(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeSpaceListResponse(BaseModel):
    spaces: list[KnowledgeSpaceResponse]
    total: int


class DocumentCreate(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    file_type: str = Field(default="txt", max_length=16)
    file_size: int = Field(default=0, ge=0)
    storage_path: str = Field(default="", max_length=512)


class DocumentUpdate(BaseModel):
    filename: str | None = Field(None, min_length=1, max_length=255)


class DocumentResponse(BaseModel):
    id: str
    space_id: str
    filename: str
    file_type: str
    file_size: int
    storage_path: str
    status: str
    chunk_count: int
    char_count: int
    created_at: datetime
    processed_at: datetime | None = None

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class ChunkResponse(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    content: str
    char_count: int
    meta: dict

    model_config = {"from_attributes": True}


class ChunkListResponse(BaseModel):
    chunks: list[ChunkResponse]
    total: int