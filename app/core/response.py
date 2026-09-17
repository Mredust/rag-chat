"""统一响应封装：成功/失败响应 + 业务异常 + 全局异常处理器。"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode:
    """业务错误码（与前端约定一致性）。"""

    SUCCESS = 0
    INVALID_PARAMETER = 40003
    TOKEN_EXPIRED = 40101
    TOKEN_INVALID = 40102
    PASSWORD_ERROR = 40103
    USER_NOT_FOUND = 40403
    DOCUMENT_NOT_FOUND = 40404
    SPACE_NOT_FOUND = 40410
    PROVIDER_NOT_FOUND = 40411
    CONVERSATION_NOT_FOUND = 40412
    ML_DATASET_NOT_FOUND = 40430
    ML_DATASET_VERSION_NOT_FOUND = 40431
    ML_MODEL_NOT_FOUND = 40432
    ML_TRAIN_TASK_NOT_FOUND = 40433
    ML_EVAL_DIMENSION_NOT_FOUND = 40434
    ML_EVAL_TASK_NOT_FOUND = 40435
    ML_LEADERBOARD_NOT_FOUND = 40436
    USERNAME_EXISTS = 40901
    EMAIL_EXISTS = 40903


_ERROR_MESSAGES = {
    ErrorCode.INVALID_PARAMETER: "参数值无效",
    ErrorCode.TOKEN_EXPIRED: "登录已过期，请重新登录",
    ErrorCode.TOKEN_INVALID: "未登录或登录已失效",
    ErrorCode.PASSWORD_ERROR: "用户名或密码错误",
    ErrorCode.USER_NOT_FOUND: "用户不存在",
    ErrorCode.DOCUMENT_NOT_FOUND: "文档不存在",
    ErrorCode.SPACE_NOT_FOUND: "知识库不存在",
    ErrorCode.PROVIDER_NOT_FOUND: "供应商不存在",
    ErrorCode.CONVERSATION_NOT_FOUND: "会话不存在",
    ErrorCode.ML_DATASET_NOT_FOUND: "数据集不存在",
    ErrorCode.ML_DATASET_VERSION_NOT_FOUND: "数据集版本不存在",
    ErrorCode.ML_MODEL_NOT_FOUND: "模型不存在",
    ErrorCode.ML_TRAIN_TASK_NOT_FOUND: "训练任务不存在",
    ErrorCode.ML_EVAL_DIMENSION_NOT_FOUND: "评测维度不存在",
    ErrorCode.ML_EVAL_TASK_NOT_FOUND: "评测任务不存在",
    ErrorCode.ML_LEADERBOARD_NOT_FOUND: "排行榜不存在",
    ErrorCode.USERNAME_EXISTS: "用户名已存在",
    ErrorCode.EMAIL_EXISTS: "该邮箱已被使用",
}


class BusinessError(Exception):
    """业务异常：由全局异常处理器转换为统一失败响应。"""

    def __init__(self, code: int, message: str | None = None, http_status: int = 400) -> None:
        self.code = code
        self.message = message or _ERROR_MESSAGES.get(code, "服务器内部错误")
        self.http_status = http_status
        super().__init__(self.message)


def success_response(data: Any = None, message: str = "ok", code: int = 0) -> dict:
    """构造统一成功响应。"""
    return {"code": code, "message": message, "data": data, "request_id": str(uuid.uuid4())}


def failed_response(code: int, message: str | None = None) -> dict:
    """构造统一失败响应。"""
    return {
        "code": code,
        "message": message or _ERROR_MESSAGES.get(code, "服务器内部错误"),
        "data": None,
        "request_id": str(uuid.uuid4()),
    }


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。"""

    @app.exception_handler(BusinessError)
    async def _business_error_handler(request: Request, exc: BusinessError):
        return JSONResponse(status_code=exc.http_status, content=failed_response(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=failed_response(ErrorCode.INVALID_PARAMETER, "请求参数校验失败"),
        )