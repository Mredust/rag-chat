"""模型训练平台数据模型：数据集（含版本）、模型、训练任务、评测维度与评测任务。

对应界面模块：
- 数据管理：ml_dataset / ml_dataset_version（上传 jsonl/xls/xlsx，管理版本与发布预览）
- 我的模型：ml_model（导入本地模型文件夹并记录系统路径）
- 模型调优：ml_train_task（SFT/DPO/CPT/RL 训练任务）
- 模型评测：ml_eval_dimension / ml_eval_task（自定义/基线评测，产出排行榜）
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class MLDataset(Base):
    """数据集：训练集或评测集，含类型/场景/训练方式/存储/导入方式等元信息。"""

    __tablename__ = "ml_dataset"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 数据集类型：train（训练集）/ eval（评测集）
    dataset_type: Mapped[str] = mapped_column(String(16), default="train", nullable=False)
    # 训练场景：text_gen / vision / image2video_first / image2video_first_last（仅训练集）
    train_scene: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 训练方式：sft / dpo / cpt（仅训练集）
    train_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 存储位置：oss（平台 OSS）/ mount（云存储挂载）
    storage_location: Mapped[str] = mapped_column(String(16), default="oss", nullable=False)
    # 导入方式：upload（本地上传）/ oss（从 OSS 导入）/ log（日志回流）
    import_method: Mapped[str] = mapped_column(String(16), default="upload", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.now(), nullable=False
    )

    versions: Mapped[list["MLDatasetVersion"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="MLDatasetVersion.version"
    )


class MLDatasetVersion(Base):
    """数据集版本：一次导入（上传/导入/回流）产生一个版本，含数据量与预览内容。"""

    __tablename__ = "ml_dataset_version"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    dataset_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("ml_dataset.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 数据量（jsonl 为行数；xls/xlsx 暂记为 0，前端显示「-」）
    data_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 导入状态：importing / done / failed
    import_status: Mapped[str] = mapped_column(String(16), default="done", nullable=False)
    # 发布状态：draft（未发布）/ published（已发布）
    publish_status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    # 文件 ID（可复制），用于在 OSS/存储中定位版本
    file_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    # 预览内容（仅保留前 ~100KB 文本，MEDIUMTEXT 以容纳 100KB 预览）
    preview_content: Mapped[str] = mapped_column(MEDIUMTEXT, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )

    dataset: Mapped["MLDataset"] = relationship(back_populates="versions")


class MLModel(Base):
    """已导入/微调产出的模型：基础模型、来源、挂载目录与供应商配置。"""

    __tablename__ = "ml_model"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    base_model: Mapped[str] = mapped_column(String(128), nullable=False)
    # 训练方式（如 LoRA）
    train_method: Mapped[str] = mapped_column(String(16), default="LoRA", nullable=False)
    # 导入来源（本地导入 / 训练产出 / 供应商 provider）
    source: Mapped[str] = mapped_column(String(16), default="upload", nullable=False)
    # 存储桶（预留字段）
    bucket: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    # 模型目录路径
    model_dir: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    # 供应商向量模型配置（source=provider 时使用）：{provider, url, api_key, model}
    provider_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 状态：importing / ready / failed
    status: Mapped[str] = mapped_column(String(16), default="ready", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.now(), nullable=False
    )


class MLTrainTask(Base):
    """训练任务：优先级、训练方式、基础模型、训练/数据/资源/产出配置与生命周期。"""

    __tablename__ = "ml_train_task"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 优先级 L0~L3（L0 最高）
    priority: Mapped[str] = mapped_column(String(4), default="L2", nullable=False)
    # 训练方式：sft / dpo / cpt / rl
    train_method: Mapped[str] = mapped_column(String(16), default="sft", nullable=False)
    base_model: Mapped[str] = mapped_column(String(128), nullable=False)
    # 训练集（关联 ml_dataset 中类型为 train 的数据集）
    dataset_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("ml_dataset.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 验证集比例（默认自动切分 10%）
    valid_ratio: Mapped[float] = mapped_column(Float, default=0.1, nullable=False)
    # 完整配置快照（训练配置 / 数据配置 / 训练资源 / 训练产出）
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # 保存模型名
    output_model_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    # 状态：pending / running / done / failed / stopped
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    output_dir: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    log: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 训练指标（图表数据：每个 epoch 的训练损失/验证损失/验证准确率/学习率等）
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.now(), nullable=False
    )

    @property
    def dataset_ids(self) -> list[str]:
        """训练集多选列表（持久化于 config.dataset_ids）。"""
        ids = (self.config or {}).get("dataset_ids")
        return [str(x) for x in ids] if isinstance(ids, list) else []


class MLEvalDimension(Base):
    """评测维度：定义一组评价指标与标准，供评测任务复用。

    eval_type 支持：
    - llm_classify   大模型评估-分类型
    - llm_numeric    大模型评估-数值型
    - rule_match     规则评估-字符串匹配
    - rule_sim       规则评估-文本相似度
    - manual         人工评估
    """

    __tablename__ = "ml_eval_dimension"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 维度类型
    eval_type: Mapped[str] = mapped_column(String(32), default="llm_classify", nullable=False)
    # 维度详细配置（评分模板、裁判模型、标签、阈值等）
    eval_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )


class MLEvalTask(Base):
    """评测任务：自定义评测或基线评测，产出指标分数并可选同步排行榜。"""

    __tablename__ = "ml_eval_task"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 评测模型（关联 ml_model）
    model_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("ml_model.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 评测模型类型：vector（向量模型） / llm（大模型）
    model_type: Mapped[str] = mapped_column(String(16), default="vector", nullable=False)
    # 大模型供应商模型 ID（model_type=llm 时使用，关联 provider.id）
    llm_model_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # 数据来源：dataset（评测数据集）/ inference（推理结果集）
    data_source: Mapped[str] = mapped_column(String(16), default="dataset", nullable=False)
    data_id: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    # 评测数据来源方式：dataset（选择测评集）/ auto_split（自动切分训练集）
    data_mode: Mapped[str] = mapped_column(String(16), default="dataset", nullable=False)
    # 自动切分使用的训练集 ID（data_mode=auto_split 时有效）
    split_dataset_id: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    # 自动切分比例（默认 10%，作为评测集）
    split_ratio: Mapped[float] = mapped_column(Float, default=0.1, nullable=False)
    # 评测维度（关联多个 ml_eval_dimension）
    dimension_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # 评测维度名称快照（维度被删除后仍能展示名称而非 ID）
    dimension_names: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # 是否同步至排行榜
    sync_leaderboard: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 同步目标排行榜（可空，选择后评测完成自动加入该排行榜）
    leaderboard_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("ml_leaderboard.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 状态：pending / running / done / failed
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    # 评测数据总量 / 已完成量
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 评测结果（指标分数列表 + 汇总）
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.now(), nullable=False
    )


class MLLeaderboard(Base):
    """排行榜：用户创建，关联评测维度并勾选若干评测任务。"""

    __tablename__ = "ml_leaderboard"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 关联评测维度（多个）
    dimension_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # 评测维度名称快照（维度被删除后仍能展示名称而非 ID）
    dimension_names: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # 关联的评测任务 ID 列表
    task_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )