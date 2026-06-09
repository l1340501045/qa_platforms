"""UploadService 单测 — 多格式上传解析（zip / 单 md / 文件夹 / 图片 / 去重信息）

MinIO 被 mock，测试只覆盖解析、分发、content/hash 计算与相对路径保留逻辑。
"""

import hashlib
import io
import zipfile
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from src.platform_api.services import upload_service as upload_module
from src.platform_api.services.upload_service import UploadService

SYS = uuid4()


@pytest.fixture(autouse=True)
def mock_minio(monkeypatch):
    """屏蔽真实 MinIO 调用"""
    puts: list[tuple[str, bytes, str]] = []

    monkeypatch.setattr(upload_module, "ensure_bucket_exists", lambda: None)

    def fake_put(bucket_name, object_name, data, length, content_type):
        puts.append((object_name, data.read(), content_type))

    monkeypatch.setattr(upload_module.minio_client, "put_object", fake_put)
    return puts


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": "application/octet-stream"}),
    )


def _make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_single_markdown_populates_content_and_hash(mock_minio):
    svc = UploadService()
    text = b"# Hello\n\xe6\xb5\x8b\xe8\xaf\x95"  # 含中文 utf-8
    outcome = await svc.process_uploads([_upload("spec.md", text)], SYS)

    assert len(outcome.documents) == 1
    doc = outcome.documents[0]
    assert doc["title"] == "spec"
    assert doc["content"] == text.decode("utf-8")
    assert doc["content_hash"] == hashlib.sha256(doc["content"].encode("utf-8")).hexdigest()
    assert doc["content_hash"]  # 非空，避免唯一约束冲突
    assert doc["folder_path"] is None
    assert outcome.total_files == 1


@pytest.mark.asyncio
async def test_zip_with_md_and_image_preserves_relative_paths(mock_minio):
    svc = UploadService()
    zip_bytes = _make_zip(
        {
            "PRD/需求.md": "![图](images/a.png)".encode("utf-8"),
            "PRD/images/a.png": b"\x89PNG\r\n\x1a\n",
            "PRD/readme.txt": b"ignore me",
        }
    )
    outcome = await svc.process_uploads([_upload("PRD.zip", zip_bytes)], SYS)

    assert len(outcome.documents) == 1
    assert outcome.documents[0]["folder_path"] == "PRD"
    assert outcome.documents[0]["storage_path"] == f"systems/{SYS}/documents/PRD/需求.md"

    assert len(outcome.images) == 1
    assert outcome.images[0]["storage_path"] == f"systems/{SYS}/documents/PRD/images/a.png"

    # 不支持的 txt 被跳过
    assert any(s["filename"] == "readme.txt" for s in outcome.skipped)


@pytest.mark.asyncio
async def test_directory_style_multiple_files(mock_minio):
    """模拟前端文件夹上传：每个文件 filename 带相对路径"""
    svc = UploadService()
    files = [
        _upload("漫剧PRD/main.md", b"# main"),
        _upload("漫剧PRD/images/cover.jpg", b"\xff\xd8\xff"),
    ]
    outcome = await svc.process_uploads(files, SYS)

    assert len(outcome.documents) == 1
    assert outcome.documents[0]["folder_path"] == "漫剧PRD"
    assert len(outcome.images) == 1
    assert outcome.total_files == 2


@pytest.mark.asyncio
async def test_no_supported_files_raises(mock_minio):
    svc = UploadService()
    with pytest.raises(HTTPException) as exc:
        await svc.process_uploads([_upload("notes.txt", b"x")], SYS)
    assert exc.value.detail["code"] == "E4006"


@pytest.mark.asyncio
async def test_bad_zip_raises(mock_minio):
    svc = UploadService()
    with pytest.raises(HTTPException) as exc:
        await svc.process_uploads([_upload("broken.zip", b"not a zip")], SYS)
    assert exc.value.detail["code"] == "E4005"
