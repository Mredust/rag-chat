"""模型训练平台 Schema：数据集（含版本）、模型、训练任务、评测维度与评测任务。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ===== 数据集 =====


class MLDatasetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field("", max_length=200)
    dataset_type: str = Field("train")
    train_scene: str | None = None
    train_method: str | None = None
    storage_location: str = Field("oss")
    import_method: str = Field("upload")


class MLDatasetResponse(BaseModel):
    id: str
    name: str
    description: str
    dataset_type: str
    train_scene: str | None
    train_method: str | None
    storage_location: str
    import_method: str
    created_at: datetime
    updated_at: datetime
    # 最新版本汇总（列表/详情用）
    latest_version: int | None = None
    latest_version_id: str | None = None
    data_count: int = 0
    import_status: str = ""
    publish_status: str = ""
    version_updated_at: datetime | None = None


class MLDatasetGenerateRequest(BaseModel):
    """生成数据集请求：选择知识库，通过预设模板 prompt 调用大模型生成格式化数据。"""

    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field("", max_length=200)
    dataset_type: str = Field("train")
    train_scene: str | None = None
    train_method: str | None = None
    space_id: str = Field(..., min_length=1)
    count: int = Field(500, ge=1, le=50000)


class MLDatasetListResponse(BaseModel):
    datasets: list[MLDatasetResponse]
    total: int


class MLDatasetVersionResponse(BaseModel):
    id: str
    dataset_id: str
    version: int
    file_count: int
    data_count: int
    import_status: str
    publish_status: str
    file_id: str
    preview_content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MLDatasetVersionListResponse(BaseModel):
    versions: list[MLDatasetVersionResponse]
    total: int


# ===== 模型 =====


class MLModelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    base_model: str = Field(..., min_length=1, max_length=128)
    train_method: str = Field("LoRA", max_length=16)
    source: str = Field("upload", max_length=16)
    bucket: str = Field("", max_length=128)
    model_dir: str = Field("", max_length=512)
    # 供应商向量模型配置（source=provider 时使用）：{provider, url, api_key, model}
    provider_config: dict | None = None


class MLModelResponse(BaseModel):
    id: str
    name: str
    base_model: str
    train_method: str
    source: str
    bucket: str
    model_dir: str
    provider_config: dict | None = None
    status: str
    # 模型目录是否位于项目 models 目录下（用于前端展示「保存到本地」按钮）
    is_local: bool = False
    # 模型来源：system（系统内置）/ ftm（微调）/ local（本地）/ provider（供应商）/ none（不在 models 下）
    source_type: str = "local"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MLModelListResponse(BaseModel):
    models: list[MLModelResponse]
    total: int


# ===== 训练任务 =====


class MLTrainTaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    priority: str = Field("L2", max_length=4)
    train_method: str = Field("sft", max_length=16)
    base_model: str = Field(..., min_length=1, max_length=128)
    dataset_id: str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    valid_ratio: float = Field(0.1, ge=0, le=1)
    config: dict = Field(default_factory=dict)
    output_model_name: str = Field("", max_length=128)


class MLTrainTaskResponse(BaseModel):
    id: str
    name: str
    priority: str
    train_method: str
    base_model: str
    dataset_id: str | None
    dataset_ids: list[str] = Field(default_factory=list)
    valid_ratio: float
    config: dict
    output_model_name: str
    status: str
    output_dir: str
    log: str
    metrics: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MLTrainTaskListResponse(BaseModel):
    tasks: list[MLTrainTaskResponse]
    total: int


# ===== 评测维度 =====


class MLEvalDimensionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=500)
    eval_type: str = Field("llm_classify", max_length=32)
    eval_config: dict = Field(default_factory=dict)


class MLEvalDimensionResponse(BaseModel):
    id: str
    name: str
    description: str
    eval_type: str
    eval_config: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class MLEvalDimensionListResponse(BaseModel):
    dimensions: list[MLEvalDimensionResponse]
    total: int


# ===== 评测任务 =====


class MLEvalTaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    model_id: str | None = None
    # 评测模型类型：vector（向量模型） / llm（大模型）
    model_type: str = Field("vector", max_length=16)
    # 大模型供应商模型 ID（model_type=llm 时使用）
    llm_model_id: str | None = None
    data_source: str = Field("dataset", max_length=16)
    data_id: str = Field("", max_length=40)
    # 评测数据来源方式：dataset（选择测评集）/ auto_split（自动切分训练集）
    data_mode: str = Field("dataset", max_length=16)
    # 自动切分使用的训练集 ID（data_mode=auto_split 时有效）
    split_dataset_id: str = Field("", max_length=40)
    # 自动切分比例（默认 10%，作为评测集）
    split_ratio: float = Field(0.1, ge=0, le=1)
    dimension_ids: list[str] = Field(default_factory=list)
    sync_leaderboard: bool = True
    leaderboard_id: str | None = None


class MLEvalTaskResponse(BaseModel):
    id: str
    name: str
    model_id: str | None
    model_name: str = ""
    model_type: str = "vector"
    llm_model_id: str | None = None
    data_source: str
    data_id: str
    data_name: str = ""
    data_mode: str = "dataset"
    split_dataset_id: str = ""
    split_ratio: float = 0.1
    dimension_ids: list[str] = Field(default_factory=list)
    dimension_names: list[str] = Field(default_factory=list)
    sync_leaderboard: bool
    leaderboard_id: str | None = None
    leaderboard_name: str = ""
    status: str
    total_count: int = 0
    completed_count: int = 0
    result: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MLEvalTaskListResponse(BaseModel):
    tasks: list[MLEvalTaskResponse]
    total: int


# ===== 排行榜 =====


class MLLeaderboardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    dimension_ids: list[str] = Field(default_factory=list)
    task_ids: list = Field(default_factory=list)


class MLLeaderboardResponse(BaseModel):
    id: str
    name: str
    dimension_ids: list[str] = Field(default_factory=list)
    dimension_names: list[str] = Field(default_factory=list)
    task_ids: list = Field(default_factory=list)
    task_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class MLLeaderboardListResponse(BaseModel):
    leaderboards: list[MLLeaderboardResponse]
    total: int


class MLLeaderboardTaskEntry(BaseModel):
    id: str
    name: str
    model_name: str = ""
    score: float = 0.0
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    created_at: datetime


class MLLeaderboardDetailResponse(MLLeaderboardResponse):
    tasks: list[MLLeaderboardTaskEntry] = Field(default_factory=list)