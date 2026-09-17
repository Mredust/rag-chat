"""API 路由聚合。"""
from fastapi import APIRouter

from app.api import auth, chat, config, knowledge, provider, ml

api_router = APIRouter()
api_router.include_router(auth.router, tags=["User & Auth"])
api_router.include_router(knowledge.router, tags=["Knowledge"])
api_router.include_router(chat.router, tags=["Chat"])
api_router.include_router(config.router, tags=["Config"])
api_router.include_router(provider.router, tags=["Provider"])
api_router.include_router(ml.router, prefix="/ml", tags=["Model Platform"])