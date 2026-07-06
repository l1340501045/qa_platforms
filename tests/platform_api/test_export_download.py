"""导出下载接口单测：已完成任务应以附件流返回，异常状态给出业务错误。"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from src.platform_api.api.v1 import exports as exports_api
from src.platform_api.core.exceptions import ApiError
from src.platform_api.core.settings import settings


class FakeStorageResponse:
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.chunk_size: int | None = None
        self.closed = False
        self.released = False

    def stream(self, chunk_size: int):
        self.chunk_size = chunk_size
        yield from self.chunks

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class FakeMinioClient:
    def __init__(self, response: FakeStorageResponse):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def get_object(self, bucket_name: str, object_name: str):
        self.calls.append((bucket_name, object_name))
        return self.response


class FailingMinioClient:
    def get_object(self, _bucket_name: str, _object_name: str):
        raise OSError("storage unavailable")


def _repo_for(task):
    class FakeRepository:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_by_id(self, _export_id):
            return task

    return FakeRepository


async def _read_response_body(response) -> bytes:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


async def test_download_export_returns_attachment_stream(monkeypatch):
    export_id = UUID("50b987ab-0000-0000-0000-000000000001")
    object_name = f"exports/{export_id}.xlsx"
    task = SimpleNamespace(
        id=export_id,
        status="completed",
        format="excel",
        file_url=f"/{settings.minio_bucket}/{object_name}",
    )
    storage_response = FakeStorageResponse([b"excel-", b"bytes"])
    minio_client = FakeMinioClient(storage_response)
    monkeypatch.setattr(exports_api, "BaseRepository", _repo_for(task))
    monkeypatch.setattr(exports_api, "minio_client", minio_client)

    response = await exports_api.download_export(export_id, session=object())
    body = await _read_response_body(response)

    assert body == b"excel-bytes"
    assert minio_client.calls == [(settings.minio_bucket, object_name)]
    assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert 'filename="qa-export-50b987ab.xlsx"' in response.headers["content-disposition"]
    assert storage_response.closed is True
    assert storage_response.released is True


def test_export_download_url_hides_storage_path():
    export_id = UUID("50b987ab-0000-0000-0000-000000000004")
    task = SimpleNamespace(
        id=export_id,
        status="completed",
        format="excel",
        file_url=f"/{settings.minio_bucket}/exports/{export_id}.xlsx",
    )

    assert exports_api._export_download_url(task) == f"/api/v1/exports/{export_id}/download"


async def test_download_export_rejects_processing_task(monkeypatch):
    export_id = UUID("50b987ab-0000-0000-0000-000000000002")
    task = SimpleNamespace(id=export_id, status="processing", format="excel", file_url=None)
    monkeypatch.setattr(exports_api, "BaseRepository", _repo_for(task))

    with pytest.raises(ApiError) as exc_info:
        await exports_api.download_export(export_id, session=object())

    assert exc_info.value.error_code == "E4092"
    assert "尚未生成" in exc_info.value.message


async def test_download_export_rejects_invalid_file_url(monkeypatch):
    export_id = UUID("50b987ab-0000-0000-0000-000000000003")
    task = SimpleNamespace(id=export_id, status="completed", format="excel", file_url="/not-export/file.xlsx")
    monkeypatch.setattr(exports_api, "BaseRepository", _repo_for(task))

    with pytest.raises(ApiError) as exc_info:
        await exports_api.download_export(export_id, session=object())

    assert exc_info.value.error_code == "E4041"
    assert "地址无效" in exc_info.value.message


async def test_download_export_maps_storage_connection_error(monkeypatch):
    export_id = UUID("50b987ab-0000-0000-0000-000000000005")
    task = SimpleNamespace(
        id=export_id,
        status="completed",
        format="excel",
        file_url=f"/{settings.minio_bucket}/exports/{export_id}.xlsx",
    )
    monkeypatch.setattr(exports_api, "BaseRepository", _repo_for(task))
    monkeypatch.setattr(exports_api, "minio_client", FailingMinioClient())

    with pytest.raises(ApiError) as exc_info:
        await exports_api.download_export(export_id, session=object())

    assert exc_info.value.error_code == "E5031"
    assert "暂时无法下载" in exc_info.value.message
