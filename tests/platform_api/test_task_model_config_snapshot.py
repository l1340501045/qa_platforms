import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.platform_api.models.enums import BatchStatus
from src.platform_api.services.document_service import DocumentService
from src.platform_api.services.generation_service import GenerationService


class FakeBatchRepository:
    def __init__(self):
        self.created_kwargs = None

    async def create(self, **kwargs):
        self.created_kwargs = kwargs
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            id=uuid.uuid4(),
            document_id=kwargs["document_id"],
            system_id=kwargs["system_id"],
            status=kwargs["status"],
            current_stage=None,
            total_cases=None,
            celery_task_id=None,
            created_at=now,
            updated_at=now,
        )


async def test_generation_dispatch_does_not_permanently_lock_batch_model_version() -> None:
    session = SimpleNamespace(flush=AsyncMock(), refresh=AsyncMock())
    service = GenerationService(session)
    service.repo = FakeBatchRepository()
    task_result = SimpleNamespace(id="celery-task-id")

    with patch("src.platform_api.services.generation_service.celery_app.send_task", return_value=task_result) as send:
        await service.trigger_generation(uuid.uuid4(), uuid.uuid4(), {"language": "zh"})

    assert "model_config_version_id" not in service.repo.created_kwargs
    assert service.repo.created_kwargs["status"] == BatchStatus.PENDING
    task_kwargs = send.call_args.kwargs["kwargs"]
    assert "api_key" not in str(task_kwargs).lower()
    assert "model_config" not in task_kwargs


async def test_document_parse_dispatch_defers_model_selection_until_worker_start() -> None:
    service = DocumentService.__new__(DocumentService)
    documents = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]

    with patch("src.platform_api.core.celery_app.celery_app.send_task") as send:
        service._trigger_kb_parsing(documents)

    assert send.call_count == 2
    for call in send.call_args_list:
        kwargs = call.kwargs["kwargs"]
        assert set(kwargs) == {"document_id"}
