"""回归测试：Celery 任务必须全部注册在同一个 celery_app 上，且 worker 可消费。

根因背景：
1. celery_app 未配置 include，worker 启动后不导入任务模块 → 任务不注册 →
   消息以 "Received unregistered task" 堆积，异步链路完全失效。
2. kb 解析任务原先定义在独立的第二个 Celery("knowledge_base") 实例上，
   且发送方任务名 "knowledge_base.tasks.parse_document" 与注册名
   "knowledge_base.parse_document" 不匹配 → 即使有 worker 也消费不了。

本测试锁定：include 覆盖两个任务模块，且关键任务名均注册在同一 celery_app 上。
"""

from src.platform_api.core.celery_app import celery_app

EXPECTED_TASKS = {
    "testcase_generator.run_pipeline",
    "testcase_generator.resume_pipeline",
    "knowledge_base.parse_document",
}


def test_include_covers_task_modules():
    include = set(celery_app.conf.include or [])
    assert "src.testcase_generator.tasks.pipeline_task" in include
    assert "src.knowledge_base.tasks.parse_task" in include


def test_all_tasks_registered_on_single_app():
    # 触发 include 模块加载（等价于 worker 启动时的注册行为）
    celery_app.loader.import_default_modules()
    registered = set(celery_app.tasks.keys())
    missing = EXPECTED_TASKS - registered
    assert not missing, f"未注册任务: {missing}"


def test_kb_parse_task_name_matches_sender():
    """kb 解析任务的注册名必须与 document_service 发送的任务名一致"""
    celery_app.loader.import_default_modules()
    assert "knowledge_base.parse_document" in celery_app.tasks
    # 旧的错误任务名不应存在
    assert "knowledge_base.tasks.parse_document" not in celery_app.tasks


def test_visibility_timeout_exceeds_long_pipeline():
    """长任务（大 PRD 生成可能 >1 小时）下，acks_late + Redis 默认 1 小时可见性超时
    会导致任务被重复投递执行。可见性超时必须显著大于默认 3600s。"""
    for key in ("broker_transport_options", "result_backend_transport_options"):
        opts = getattr(celery_app.conf, key) or {}
        assert opts.get("visibility_timeout", 0) >= 7200, f"{key} 可见性超时过短，长任务会被重复执行"
