import uuid

from src.platform_api.core.celery_app import celery_app
from src.platform_api.tasks.kb_integration import trigger_kb_parse


def test_legacy_kb_task_delegates_and_defers_model_selection_to_worker(monkeypatch) -> None:
    document_id = str(uuid.uuid4())
    sent: dict = {}

    class _Result:
        id = "delegated-task-id"

    def _send_task(name, *, kwargs, queue):
        sent.update(name=name, kwargs=kwargs, queue=queue)
        return _Result()

    monkeypatch.setattr(celery_app, "send_task", _send_task)

    result = trigger_kb_parse.run(document_id)

    assert sent == {
        "name": "knowledge_base.parse_document",
        "kwargs": {"document_id": document_id},
        "queue": "kb_parsing",
    }
    assert result == {
        "status": "delegated",
        "document_id": document_id,
        "task_id": "delegated-task-id",
    }


def test_legacy_kb_task_returns_only_safe_fixed_error(monkeypatch, caplog) -> None:
    document_id = str(uuid.uuid4())
    secret = "sk-provider-secret-in-error"

    def _send_task(*_args, **_kwargs):
        raise RuntimeError(f"upstream rejected key {secret}")

    monkeypatch.setattr(celery_app, "send_task", _send_task)

    result = trigger_kb_parse.run(document_id)

    assert result == {
        "status": "failed",
        "document_id": document_id,
        "error": "KB_PARSE_DELEGATION_FAILED",
        "error_type": "RuntimeError",
    }
    assert secret not in str(result)
    assert secret not in caplog.text
