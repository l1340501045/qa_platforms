"""Celery 应用配置"""

import os

from celery import Celery
from celery.signals import worker_process_init

from src.platform_api.core.settings import settings

celery_app = Celery(
    "qa_platforms",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    # 关键：worker 启动时自动导入任务模块，否则任务不会注册，消息会以
    # "Received unregistered task" 报错堆积在队列里（生产异步链路完全失效）。
    include=[
        "src.testcase_generator.tasks.pipeline_task",
        "src.knowledge_base.tasks.parse_task",
        "src.platform_api.tasks.export_task",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # 质量优先，一次只取一个任务
    task_soft_time_limit=None,  # 不设超时（质量优先）
    task_time_limit=None,
    # 关键：acks_late + Redis 默认 visibility_timeout=3600s 会让运行超 1 小时的任务被
    # 误判为丢失并「重新投递」→ 同一批被两个 worker 重复执行。大 PRD 生成可能跑 >1 小时，
    # 故把可见性超时放大到 6 小时，避免长任务重复执行。
    broker_transport_options={"visibility_timeout": 21600},
    result_backend_transport_options={"visibility_timeout": 21600},
)


@worker_process_init.connect
def _init_worker_db_mode(**_kwargs):
    """每个 worker 子进程启动即切到 DB NullPool 模式。

    Celery 任务用 asyncio.run() 每次新建事件循环；进程级 QueuePool 会把上一个
    任务（其事件循环已关闭）的 asyncpg 连接复用到新循环，触发
    "got Future attached to a different loop" 崩溃（长驻 worker 跑第二个任务必现）。
    NullPool 每次用完即弃连接，从根上规避跨循环复用。

    通过信号自动设置，避免依赖启动命令手动传 QA_WORKER_MODE=1 而遗漏。
    reset_engine 清掉 fork 前可能已被创建的 QueuePool engine 单例。
    """
    os.environ["QA_WORKER_MODE"] = "1"
    from src.platform_api.core.database import reset_engine

    reset_engine()
