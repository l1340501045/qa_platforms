"""Redis Checkpoint 配置 — LangGraph 断点续跑持久化"""

from langgraph.checkpoint.redis import RedisSaver

from src.platform_api.core.settings import settings


def get_redis_saver() -> RedisSaver:
    """获取 LangGraph RedisSaver 实例（用于流水线断点续跑）"""
    return RedisSaver(redis_url=settings.redis_url)
