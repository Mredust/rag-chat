"""模型训练平台路由：数据管理 / 我的模型 / 模型调优 / 模型评测。

位于 `/api/v1/ml` 前缀下。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import BusinessError, ErrorCode, success_response
from app.core.security import get_current_user_id
from app.db.database import get_db
from app.schemas.ml import (
    MLDatasetCreate,
    MLDatasetGenerateRequest,
    MLDatasetListResponse,
    MLDatasetResponse,
    MLDatasetVersionListResponse,
    MLDatasetVersionResponse,
    MLEvalDimensionCreate,
    MLEvalDimensionListResponse,
    MLEvalDimensionResponse,
    MLEvalDimensionUpdate,
    MLEvalTaskCreate,
    MLEvalTaskListResponse,
    MLEvalTaskResponse,
    MLLeaderboardCreate,
    MLLeaderboardDetailResponse,
    MLLeaderboardListResponse,
    MLLeaderboardResponse,
    MLLeaderboardTaskEntry,
    MLModelCreate,
    MLModelListResponse,
    MLModelResponse,
    MLTrainTaskCreate,
    MLTrainTaskListResponse,
    MLTrainTaskResponse,
)
from app.services import ml_service

router = APIRouter()

logger = logging.getLogger(__name__)

_ALLOWED_DATASET_TYPES = {"jsonl"}
_MAX_FILES = 10
_MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB


def _validate_jsonl_content(filename: str, content: bytes) -> None:
    """预检查文件内容是否符合 JSONL 格式：每行一个 JSON 对象，且含 query/positive/negative 字段。"""
    text = content.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER, message=f"文件「{filename}」内容为空", http_status=400
        )
    # 整体是 JSON 数组（非 JSONL），直接拒绝
    if text.startswith("["):
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER,
            message=f"文件「{filename}」是 JSON 数组格式，请上传每行一个 JSON 对象的 JSONL 文件",
            http_status=400,
        )
    required = ("query", "positive", "negative")
    for i, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            raise BusinessError(
                ErrorCode.INVALID_PARAMETER,
                message=f"文件「{filename}」第 {i} 行不是合法 JSON",
                http_status=400,
            )
        if not isinstance(obj, dict):
            raise BusinessError(
                ErrorCode.INVALID_PARAMETER,
                message=f"文件「{filename}」第 {i} 行不是 JSON 对象",
                http_status=400,
            )
        missing = [k for k in required if not str(obj.get(k, "")).strip()]
        if missing:
            raise BusinessError(
                ErrorCode.INVALID_PARAMETER,
                message=f"文件「{filename}」第 {i} 行缺少字段：{', '.join(missing)}",
                http_status=400,
            )


async def _validate_dataset_files(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    if len(files) > _MAX_FILES:
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="最多上传 10 个文件", http_status=400)
    if not files:
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="请选择需要上传的文件", http_status=400)

    result: list[tuple[str, bytes]] = []
    for f in files:
        filename = (f.filename or "untitled.jsonl").strip()
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jsonl"
        if suffix not in _ALLOWED_DATASET_TYPES:
            raise BusinessError(
                ErrorCode.INVALID_PARAMETER, message="仅支持 jsonl 格式", http_status=400
            )
        content = await f.read()
        if len(content) > _MAX_FILE_SIZE:
            raise BusinessError(
                ErrorCode.INVALID_PARAMETER, message=f"文件「{filename}」超过 200MB", http_status=400
            )
        if not content:
            raise BusinessError(ErrorCode.INVALID_PARAMETER, message=f"文件「{filename}」为空", http_status=400)
        _validate_jsonl_content(filename, content)
        result.append((filename, content))
    return result


# ===== 选项 =====


@router.get("/options", summary="平台选项（基础模型/场景/训练方式/模型目录）")
async def get_options(_: str = Depends(get_current_user_id)):
    return success_response(data=ml_service.options_payload())


# ===== 数据管理 =====


@router.post("/datasets", summary="创建数据集")
async def create_dataset(
    data: MLDatasetCreate,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    dataset = await ml_service.create_dataset(db, data)
    return success_response(data=MLDatasetResponse(**ml_service.serialize_dataset(dataset, None)).model_dump(mode="json"))


@router.post("/datasets/upload", summary="创建数据集并上传文件（校验通过后再入库）")
async def create_dataset_upload(
    name: str = Form(..., min_length=1, max_length=50),
    description: str = Form(""),
    dataset_type: str = Form("train"),
    train_scene: str | None = Form(None),
    train_method: str | None = Form(None),
    files: list[UploadFile] = File(...),
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    # 先校验 JSONL 内容，校验失败直接返回错误，不创建数据集与版本
    parsed = await _validate_dataset_files(files)
    data = MLDatasetCreate(
        name=name.strip(),
        description=description.strip(),
        dataset_type=dataset_type,
        train_scene=train_scene,
        train_method=train_method,
        storage_location="oss",
        import_method="upload",
    )
    dataset = await ml_service.create_dataset(db, data)
    version = await ml_service.create_version(db, dataset, parsed)
    return success_response(
        data=MLDatasetResponse(**ml_service.serialize_dataset(dataset, version)).model_dump(mode="json")
    )


@router.post("/datasets/generate", summary="生成数据集（选择知识库，调用大模型生成格式化数据）")
async def generate_dataset(
    data: MLDatasetGenerateRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    dataset = await ml_service.generate_dataset(db, data, user_id)
    version = await ml_service.get_latest_version(db, dataset.id)
    return success_response(data=MLDatasetResponse(**ml_service.serialize_dataset(dataset, version)).model_dump(mode="json"))


@router.get("/datasets", summary="数据集列表")
async def list_datasets(
    dataset_type: str | None = Query(None),
    storage: str | None = Query(None),
    import_method: str | None = Query(None),
    search: str | None = Query(None),
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    datasets = await ml_service.list_datasets(db, dataset_type, storage, import_method, search)
    items = []
    for d in datasets:
        v = await ml_service.get_latest_version(db, d.id)
        items.append(MLDatasetResponse(**ml_service.serialize_dataset(d, v)))
    return success_response(data=MLDatasetListResponse(datasets=items, total=len(items)).model_dump(mode="json"))


async def _get_dataset_or_404(db: AsyncSession, dataset_id: str):
    dataset = await ml_service.get_dataset(db, dataset_id)
    if not dataset:
        raise BusinessError(ErrorCode.ML_DATASET_NOT_FOUND, http_status=404)
    return dataset


@router.get("/datasets/{dataset_id}", summary="数据集详情")
async def get_dataset(
    dataset_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _get_dataset_or_404(db, dataset_id)
    version = await ml_service.get_latest_version(db, dataset_id)
    return success_response(data=MLDatasetResponse(**ml_service.serialize_dataset(dataset, version)).model_dump(mode="json"))


@router.delete("/datasets/{dataset_id}", summary="删除数据集")
async def delete_dataset(
    dataset_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _get_dataset_or_404(db, dataset_id)
    await ml_service.delete_dataset(db, dataset)
    return success_response(message="删除成功")


async def _get_version_or_404(db: AsyncSession, dataset_id: str, version_id: str):
    version = await ml_service.get_version(db, version_id)
    if not version or version.dataset_id != dataset_id:
        raise BusinessError(ErrorCode.ML_DATASET_VERSION_NOT_FOUND, http_status=404)
    return version


@router.get("/datasets/{dataset_id}/versions", summary="数据集版本列表")
async def list_versions(
    dataset_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _get_dataset_or_404(db, dataset_id)
    versions = await ml_service.list_versions(db, dataset_id)
    return success_response(
        data=MLDatasetVersionListResponse(
            versions=[MLDatasetVersionResponse.model_validate(v) for v in versions],
            total=len(versions),
        ).model_dump(mode="json")
    )


@router.get("/datasets/{dataset_id}/versions/{version_id}", summary="数据集版本详情（含预览）")
async def get_version(
    dataset_id: str,
    version_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    version = await _get_version_or_404(db, dataset_id, version_id)
    return success_response(data=MLDatasetVersionResponse.model_validate(version).model_dump(mode="json"))


@router.post("/datasets/{dataset_id}/versions", summary="新增数据集版本（上传文件）")
async def create_version(
    dataset_id: str,
    files: list[UploadFile] = File(...),
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _get_dataset_or_404(db, dataset_id)
    parsed = await _validate_dataset_files(files)
    version = await ml_service.create_version(db, dataset, parsed)
    return success_response(data=MLDatasetVersionResponse.model_validate(version).model_dump(mode="json"))


@router.post("/datasets/{dataset_id}/versions/{version_id}/publish", summary="发布版本")
async def publish_version(
    dataset_id: str,
    version_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    version = await _get_version_or_404(db, dataset_id, version_id)
    version = await ml_service.publish_version(db, version)
    return success_response(data=MLDatasetVersionResponse.model_validate(version).model_dump(mode="json"))


@router.delete("/datasets/{dataset_id}/versions/{version_id}", summary="删除版本")
async def delete_version(
    dataset_id: str,
    version_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    version = await _get_version_or_404(db, dataset_id, version_id)
    await ml_service.delete_version(db, version)
    return success_response(message="删除成功")


# ===== 我的模型 =====


@router.post("/models", summary="导入模型")
async def create_model(
    data: MLModelCreate,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    model = await ml_service.create_model(db, data)
    return success_response(data=MLModelResponse.model_validate(model).model_dump(mode="json"))


@router.post("/models/import", summary="导入模型（基础模型二选一：选择已有模型或导入模型文件夹）")
async def import_model(
    name: str = Form(..., min_length=1, max_length=50),
    base_model: str = Form("", max_length=128),
    files: list[UploadFile] | None = File(None),
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    has_files = bool(files)
    has_base = bool(base_model.strip())
    file_names = [f.filename for f in files] if files else []
    logger.info(
        "导入模型: name=%r base_model=%r has_files=%s has_base=%s file_count=%d files=%s",
        name, base_model, has_files, has_base, len(file_names), file_names,
    )
    # 二选一：只能选择已有模型或导入文件夹，不能两者都有、也不能两者都无
    if has_files == has_base:
        logger.warning(
            "导入模型参数校验失败（二选一）: name=%r has_files=%s has_base=%s",
            name, has_files, has_base,
        )
        raise BusinessError(
            ErrorCode.INVALID_PARAMETER,
            message="基础模型需二选一：选择已有模型或导入模型文件夹",
            http_status=400,
        )
    if has_files:
        entries = [(f.filename or "", await f.read()) for f in files]
        model = await ml_service.start_model_import(db, name.strip(), entries)
    else:
        model = await ml_service.import_model_from_existing(db, name.strip(), base_model.strip())
    logger.info("导入模型成功: model_id=%s name=%r", model.id, model.name)
    return success_response(data=MLModelResponse(**ml_service.serialize_model(model)).model_dump(mode="json"))


@router.post("/models/import-provider", summary="导入供应商向量模型")
async def import_provider_model(
    name: str = Form(..., min_length=1, max_length=50),
    provider: str = Form("阿里云"),
    url: str = Form(""),
    api_key: str = Form(""),
    model_name: str = Form(""),
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    model = await ml_service.import_provider_model(
        db, name.strip(), provider, url, api_key, model_name
    )
    return success_response(data=MLModelResponse(**ml_service.serialize_model(model)).model_dump(mode="json"))


@router.get("/models", summary="模型列表")
async def list_models(
    search: str | None = Query(None),
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    models = await ml_service.list_models(db, search)
    return success_response(
        data=MLModelListResponse(
            models=[MLModelResponse(**ml_service.serialize_model(m)) for m in models],
            total=len(models),
        ).model_dump(mode="json")
    )


async def _get_model_or_404(db: AsyncSession, model_id: str):
    model = await ml_service.get_model(db, model_id)
    if not model:
        raise BusinessError(ErrorCode.ML_MODEL_NOT_FOUND, http_status=404)
    return model


@router.delete("/models/{model_id}", summary="删除模型（可勾选同时删除本地模型文件）")
async def delete_model(
    model_id: str,
    delete_local: bool = Query(False),
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    model = await _get_model_or_404(db, model_id)
    await ml_service.delete_model(db, model, delete_local)
    return success_response(message="删除成功")


@router.post("/models/{model_id}/save-local", summary="保存模型到本地 models 目录")
async def save_model_local(
    model_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    model = await _get_model_or_404(db, model_id)
    model = await ml_service.save_model_local(db, model)
    return success_response(
        data=MLModelResponse(**ml_service.serialize_model(model)).model_dump(mode="json"),
        message="已保存到本地",
    )


# ===== 模型调优 =====


@router.post("/train-tasks", summary="创建训练任务")
async def create_train_task(
    data: MLTrainTaskCreate,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if data.dataset_id:
        await _get_dataset_or_404(db, data.dataset_id)
    task = await ml_service.create_train_task(db, data)
    return success_response(data=MLTrainTaskResponse.model_validate(task).model_dump(mode="json"))


@router.get("/train-tasks", summary="训练任务列表")
async def list_train_tasks(
    priority: str | None = Query(None),
    base_model: str | None = Query(None),
    search: str | None = Query(None),
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    tasks = await ml_service.list_train_tasks(db, priority, base_model, search)
    return success_response(
        data=MLTrainTaskListResponse(
            tasks=[MLTrainTaskResponse.model_validate(t) for t in tasks],
            total=len(tasks),
        ).model_dump(mode="json")
    )


async def _get_train_task_or_404(db: AsyncSession, task_id: str):
    task = await ml_service.get_train_task(db, task_id)
    if not task:
        raise BusinessError(ErrorCode.ML_TRAIN_TASK_NOT_FOUND, http_status=404)
    return task


@router.get("/train-tasks/{task_id}", summary="训练任务详情")
async def get_train_task(
    task_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_train_task_or_404(db, task_id)
    return success_response(data=MLTrainTaskResponse.model_validate(task).model_dump(mode="json"))


@router.post("/train-tasks/{task_id}/stop", summary="停止训练任务")
async def stop_train_task(
    task_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_train_task_or_404(db, task_id)
    task = await ml_service.stop_train_task(db, task)
    return success_response(data=MLTrainTaskResponse.model_validate(task).model_dump(mode="json"))


@router.post("/train-tasks/{task_id}/resume", summary="恢复训练任务")
async def resume_train_task(
    task_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_train_task_or_404(db, task_id)
    task = await ml_service.resume_train_task(db, task)
    return success_response(data=MLTrainTaskResponse.model_validate(task).model_dump(mode="json"))


@router.post("/train-tasks/{task_id}/export", summary="启动异步导出训练产出模型")
async def start_export_train_task(
    task_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_train_task_or_404(db, task_id)
    base_dir = await ml_service.resolve_export_base_dir(db, task.base_model)
    status = ml_service.start_export_job(task, base_dir)
    return success_response(data=status, message="导出任务已启动")


@router.get("/train-tasks/{task_id}/export/status", summary="查询导出进度")
async def export_train_task_status(
    task_id: str,
    _: str = Depends(get_current_user_id),
):
    status = ml_service.get_export_status(task_id)
    if status is None:
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="尚未发起导出", http_status=404)
    return success_response(data=status)


@router.get("/train-tasks/{task_id}/export/download", summary="下载已导出的模型文件")
async def download_export_train_task(
    task_id: str,
    _: str = Depends(get_current_user_id),
):
    status = ml_service.get_export_status(task_id)
    if status is None or status["state"] != "done" or not status.get("file_path"):
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="导出尚未完成", http_status=400)
    file_path = Path(status["file_path"])
    if not file_path.is_file():
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="导出文件不存在", http_status=404)
    filename = status.get("filename") or f"{task_id}.zip"
    return FileResponse(path=str(file_path), filename=filename, media_type="application/zip")


@router.delete("/train-tasks/{task_id}", summary="删除训练任务")
async def delete_train_task(
    task_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_train_task_or_404(db, task_id)
    await ml_service.delete_train_task(db, task)
    return success_response(message="删除成功")


@router.post("/train-tasks/{task_id}/save-model", summary="启动异步保存训练产出到我的模型")
async def save_train_task_model(
    task_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_train_task_or_404(db, task_id)
    status = ml_service.start_save_model_job(task)
    return success_response(data=status, message="保存任务已启动")


@router.get("/train-tasks/{task_id}/save-model/status", summary="查询保存进度")
async def save_train_task_model_status(
    task_id: str,
    _: str = Depends(get_current_user_id),
):
    status = ml_service.get_save_model_status(task_id)
    if status is None:
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="尚未发起保存", http_status=404)
    return success_response(data=status)


# ===== 模型评测 =====


@router.get("/dimensions", summary="评测维度列表")
async def list_dimensions(
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    dims = await ml_service.list_dimensions(db)
    return success_response(
        data=MLEvalDimensionListResponse(
            dimensions=[MLEvalDimensionResponse.model_validate(d) for d in dims],
            total=len(dims),
        ).model_dump(mode="json")
    )


@router.get("/dimensions/{dimension_id}", summary="评测维度详情")
async def get_dimension(
    dimension_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    dim = await _get_dimension_or_404(db, dimension_id)
    return success_response(data=MLEvalDimensionResponse.model_validate(dim).model_dump(mode="json"))


@router.post("/dimensions", summary="创建评测维度")
async def create_dimension(
    data: MLEvalDimensionCreate,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    dim = await ml_service.create_dimension(db, data)
    return success_response(data=MLEvalDimensionResponse.model_validate(dim).model_dump(mode="json"))


@router.put("/dimensions/{dimension_id}", summary="更新评测维度")
async def update_dimension(
    dimension_id: str,
    data: MLEvalDimensionUpdate,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    dim = await _get_dimension_or_404(db, dimension_id)
    dim = await ml_service.update_dimension(db, dim, data)
    return success_response(data=MLEvalDimensionResponse.model_validate(dim).model_dump(mode="json"))


@router.get("/eval-prompt-templates", summary="大模型评估评分器模板")
async def get_eval_prompt_templates(_: str = Depends(get_current_user_id)):
    return success_response(data=ml_service.get_eval_prompt_templates())


@router.delete("/dimensions/{dimension_id}", summary="删除评测维度")
async def delete_dimension(
    dimension_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    dim = await _get_dimension_or_404(db, dimension_id)
    await ml_service.delete_dimension(db, dim)
    return success_response(message="删除成功")


async def _serialize_eval_task(db: AsyncSession, task) -> MLEvalTaskResponse:
    dimension_ids = list(task.dimension_ids or [])
    # 自动切分模式下评测数据来源于训练集，名称解析使用 split_dataset_id
    display_data_id = task.split_dataset_id if (task.data_mode or "dataset") == "auto_split" else task.data_id
    model_name, resolved_names, data_name = await ml_service.resolve_names(
        db, task.model_id, task.model_type, task.llm_model_id, dimension_ids, display_data_id
    )
    # 优先使用创建时快照名称，避免维度删除后回退显示 ID
    stored_names = list(task.dimension_names or [])
    dimension_names = stored_names if stored_names else resolved_names
    leaderboard_name = ""
    if task.leaderboard_id:
        lb = await ml_service.get_leaderboard(db, task.leaderboard_id)
        leaderboard_name = lb.name if lb else ""
    return MLEvalTaskResponse(
        id=task.id,
        name=task.name,
        model_id=task.model_id,
        model_name=model_name,
        model_type=task.model_type,
        llm_model_id=task.llm_model_id,
        data_source=task.data_source,
        data_id=task.data_id,
        data_name=data_name,
        data_mode=getattr(task, "data_mode", "dataset") or "dataset",
        split_dataset_id=getattr(task, "split_dataset_id", "") or "",
        split_ratio=float(getattr(task, "split_ratio", 0.1) or 0.1),
        dimension_ids=dimension_ids,
        dimension_names=dimension_names,
        sync_leaderboard=task.sync_leaderboard,
        leaderboard_id=task.leaderboard_id,
        leaderboard_name=leaderboard_name,
        status=task.status,
        total_count=task.total_count,
        completed_count=task.completed_count,
        result=task.result,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post("/eval-tasks", summary="创建评测任务")
async def create_eval_task(
    data: MLEvalTaskCreate,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await ml_service.create_eval_task(db, data)
    return success_response(data=(await _serialize_eval_task(db, task)).model_dump(mode="json"))


@router.get("/eval-tasks", summary="评测任务列表")
async def list_eval_tasks(
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    tasks = await ml_service.list_eval_tasks(db)
    items = [await _serialize_eval_task(db, t) for t in tasks]
    return success_response(
        data=MLEvalTaskListResponse(tasks=items, total=len(items)).model_dump(mode="json")
    )


async def _get_eval_task_or_404(db: AsyncSession, task_id: str):
    task = await ml_service.get_eval_task(db, task_id)
    if not task:
        raise BusinessError(ErrorCode.ML_EVAL_TASK_NOT_FOUND, http_status=404)
    return task


@router.get("/eval-tasks/{task_id}", summary="评测任务详情")
async def get_eval_task(
    task_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_eval_task_or_404(db, task_id)
    return success_response(data=(await _serialize_eval_task(db, task)).model_dump(mode="json"))


@router.get("/eval-tasks/{task_id}/details", summary="评测任务数据明细（分页+关键词搜索）")
async def list_eval_task_details(
    task_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    field: str | None = Query(None),
    keyword: str | None = Query(None),
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_eval_task_or_404(db, task_id)
    items, total = ml_service.list_eval_task_details(task, field, keyword, page, page_size)
    return success_response(
        data={"items": items, "total": total, "page": page, "page_size": page_size}
    )


@router.get("/eval-tasks/{task_id}/export", summary="导出评测结果（xlsx）")
async def export_eval_task(
    task_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_eval_task_or_404(db, task_id)
    if task.status != "done":
        raise BusinessError(ErrorCode.INVALID_PARAMETER, message="仅评测完成的任务可导出", http_status=400)
    content = ml_service.build_eval_task_xlsx(task)
    filename = f"{task.name}.xlsx"
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )


@router.post("/eval-tasks/{task_id}/stop", summary="终止评测任务")
async def stop_eval_task(
    task_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_eval_task_or_404(db, task_id)
    task = await ml_service.stop_eval_task(db, task)
    return success_response(data=(await _serialize_eval_task(db, task)).model_dump(mode="json"))


@router.delete("/eval-tasks/{task_id}", summary="删除评测任务")
async def delete_eval_task(
    task_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_eval_task_or_404(db, task_id)
    if task.leaderboard_id:
        lb = await ml_service.get_leaderboard(db, task.leaderboard_id)
        if lb:
            await ml_service.remove_leaderboard_task(db, lb, task.id)
    await db.delete(task)
    await db.commit()
    return success_response(message="删除成功")


async def _get_dimension_or_404(db: AsyncSession, dimension_id: str):
    dim = await ml_service.get_dimension(db, dimension_id)
    if not dim:
        raise BusinessError(ErrorCode.ML_EVAL_DIMENSION_NOT_FOUND, http_status=404)
    return dim


@router.get("/leaderboards", summary="排行榜列表")
async def list_leaderboards(
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    items = await ml_service.list_leaderboards(db)
    return success_response(
        data=MLLeaderboardListResponse(
            leaderboards=[await _serialize_leaderboard(db, lb) for lb in items],
            total=len(items),
        ).model_dump(mode="json")
    )


async def _serialize_leaderboard(db: AsyncSession, lb) -> MLLeaderboardResponse:
    dimension_ids = list(lb.dimension_ids or [])
    # 优先使用创建时快照名称，避免维度删除后回退显示 ID
    stored_names = list(lb.dimension_names or [])
    dimension_names = stored_names or await ml_service._dimension_names(db, dimension_ids)
    return MLLeaderboardResponse(
        id=lb.id,
        name=lb.name,
        dimension_ids=dimension_ids,
        dimension_names=dimension_names,
        task_ids=list(lb.task_ids or []),
        task_count=len(lb.task_ids or []),
        created_at=lb.created_at,
    )


async def _get_leaderboard_or_404(db: AsyncSession, leaderboard_id: str):
    lb = await ml_service.get_leaderboard(db, leaderboard_id)
    if not lb:
        raise BusinessError(ErrorCode.ML_LEADERBOARD_NOT_FOUND, http_status=404)
    return lb


@router.post("/leaderboards", summary="创建排行榜")
async def create_leaderboard(
    data: MLLeaderboardCreate,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    for did in data.dimension_ids:
        await _get_dimension_or_404(db, did)
    lb = await ml_service.create_leaderboard(db, data)
    return success_response(data=(await _serialize_leaderboard(db, lb)).model_dump(mode="json"))


@router.put("/leaderboards/{leaderboard_id}", summary="更新排行榜")
async def update_leaderboard(
    leaderboard_id: str,
    data: MLLeaderboardCreate,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    lb = await _get_leaderboard_or_404(db, leaderboard_id)
    for did in data.dimension_ids:
        await _get_dimension_or_404(db, did)
    lb = await ml_service.update_leaderboard(db, lb, data)
    return success_response(data=(await _serialize_leaderboard(db, lb)).model_dump(mode="json"))


@router.delete("/leaderboards/{leaderboard_id}", summary="删除排行榜")
async def delete_leaderboard(
    leaderboard_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    lb = await _get_leaderboard_or_404(db, leaderboard_id)
    await ml_service.delete_leaderboard(db, lb)
    return success_response(message="删除成功")


@router.get("/leaderboards/{leaderboard_id}", summary="排行榜详情")
async def get_leaderboard(
    leaderboard_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    lb = await _get_leaderboard_or_404(db, leaderboard_id)
    base = await _serialize_leaderboard(db, lb)
    tasks: list[MLLeaderboardTaskEntry] = []
    for tid in lb.task_ids or []:
        task = await ml_service.get_eval_task(db, tid)
        if not task:
            continue
        model_name = await ml_service.resolve_model_name(
            db, task.model_id, task.model_type, task.llm_model_id
        )
        score = (task.result or {}).get("score")
        dimension_scores: dict[str, float] = {}
        for m in (task.result or {}).get("metrics") or []:
            if isinstance(m, dict) and m.get("name"):
                try:
                    dimension_scores[str(m["name"])] = round(float(m.get("score", 0.0)), 4)
                except (TypeError, ValueError):
                    dimension_scores[str(m["name"])] = 0.0
        tasks.append(
            MLLeaderboardTaskEntry(
                id=task.id,
                name=task.name,
                model_name=model_name,
                score=round(float(score), 4) if isinstance(score, (int, float)) else 0.0,
                dimension_scores=dimension_scores,
                created_at=task.created_at,
            )
        )
    return success_response(
        data=MLLeaderboardDetailResponse(
            id=base.id,
            name=base.name,
            dimension_ids=base.dimension_ids,
            dimension_names=base.dimension_names,
            task_ids=base.task_ids,
            task_count=base.task_count,
            created_at=base.created_at,
            tasks=tasks,
        ).model_dump(mode="json")
    )


@router.delete("/leaderboards/{leaderboard_id}/tasks/{task_id}", summary="从排行榜移除评测任务")
async def remove_leaderboard_task(
    leaderboard_id: str,
    task_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    lb = await _get_leaderboard_or_404(db, leaderboard_id)
    await ml_service.remove_leaderboard_task(db, lb, task_id)
    return success_response(message="移除成功")