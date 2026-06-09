"""文件上传处理 — 支持 zip / 单个 .md / 文件夹（含图片）

支持的上传形态：
1. zip 压缩包：解压后提取 .md 与图片文件
2. 单个 .md 文件
3. 文件夹（前端 webkitdirectory 上传）：每个文件 filename 携带相对路径

处理规则：
- .md 文件：读取文本写入 content、计算 content_hash，并存入 MinIO，生成文档条目
- 图片文件：按相对路径存入 MinIO（与同目录 .md 共享前缀，保证相对引用可解析），不生成文档
- 其它格式：跳过
"""

import hashlib
import io
import os
import zipfile
from dataclasses import dataclass, field
from uuid import UUID

from fastapi import HTTPException, UploadFile

from src.platform_api.core.minio_client import ensure_bucket_exists, minio_client
from src.platform_api.core.settings import settings

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
IMAGE_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}


@dataclass
class UploadOutcome:
    """一次上传的处理结果汇总"""

    documents: list[dict] = field(default_factory=list)  # 待入库的 .md 文档信息
    images: list[dict] = field(default_factory=list)  # 已存储的图片资产
    skipped: list[dict] = field(default_factory=list)  # {filename, reason}
    failed: list[dict] = field(default_factory=list)  # {filename, error}
    total_files: int = 0


class UploadService:
    """处理文件上传：解析多形态输入 → 过滤 → MinIO 存储"""

    def __init__(self):
        ensure_bucket_exists()

    async def process_uploads(
        self,
        files: list[UploadFile],
        system_id: UUID,
    ) -> UploadOutcome:
        """处理一组上传文件（可能是 zip、单 md、文件夹内的多个文件）"""
        outcome = UploadOutcome()

        if not files:
            raise HTTPException(
                status_code=400,
                detail={"code": "E4004", "message": "未提供任何上传文件", "details": None},
            )

        for upload in files:
            filename = upload.filename or ""
            content = await upload.read()

            if filename.lower().endswith(".zip"):
                self._process_zip(content, system_id, outcome)
            else:
                outcome.total_files += 1
                self._process_single(filename, content, system_id, outcome)

        if not outcome.documents and not outcome.images:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "E4006",
                    "message": "未找到可上传的 .md 或图片文件",
                    "details": None,
                },
            )

        return outcome

    # ─── zip 处理 ───

    def _process_zip(self, content: bytes, system_id: UUID, outcome: UploadOutcome) -> None:
        try:
            zip_file = zipfile.ZipFile(io.BytesIO(content), "r")
        except zipfile.BadZipFile:
            raise HTTPException(
                status_code=400,
                detail={"code": "E4005", "message": "无效的 zip 文件", "details": None},
            )

        with zip_file:
            for zip_info in zip_file.infolist():
                if zip_info.is_dir():
                    continue
                if "__MACOSX" in zip_info.filename:
                    continue
                outcome.total_files += 1
                self._process_single(
                    zip_info.filename,
                    zip_file.read(zip_info.filename),
                    system_id,
                    outcome,
                )

    # ─── 单文件分发 ───

    def _process_single(
        self,
        relative_path: str,
        file_content: bytes,
        system_id: UUID,
        outcome: UploadOutcome,
    ) -> None:
        """根据扩展名把单个文件分发到 md / 图片 / 跳过"""
        # 统一为 posix 风格相对路径
        relative_path = relative_path.replace("\\", "/").lstrip("/")
        ext = os.path.splitext(relative_path)[1].lower()

        try:
            if ext == ".md":
                self._handle_markdown(relative_path, file_content, system_id, outcome)
            elif ext in IMAGE_EXTENSIONS:
                self._handle_image(relative_path, file_content, system_id, outcome, ext)
            else:
                outcome.skipped.append(
                    {
                        "filename": os.path.basename(relative_path) or relative_path,
                        "reason": "不支持的文件格式，仅接受 .md 和图片文件",
                    }
                )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — 单文件失败不应中断整批
            outcome.failed.append(
                {"filename": os.path.basename(relative_path) or relative_path, "error": str(exc)}
            )

    def _handle_markdown(
        self, relative_path: str, file_content: bytes, system_id: UUID, outcome: UploadOutcome
    ) -> None:
        text = file_content.decode("utf-8-sig", errors="replace")
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        storage_path = self._storage_path(system_id, relative_path)
        folder_path = os.path.dirname(relative_path) or None
        file_name = os.path.basename(relative_path)

        self._put(storage_path, file_content, "text/markdown")

        outcome.documents.append(
            {
                "title": file_name[: -len(".md")] if file_name.endswith(".md") else file_name,
                "storage_path": storage_path,
                "folder_path": folder_path,
                "content": text,
                "content_hash": content_hash,
                "metadata": {
                    "original_filename": relative_path,
                    "file_size": len(file_content),
                },
            }
        )

    def _handle_image(
        self,
        relative_path: str,
        file_content: bytes,
        system_id: UUID,
        outcome: UploadOutcome,
        ext: str,
    ) -> None:
        storage_path = self._storage_path(system_id, relative_path)
        self._put(storage_path, file_content, IMAGE_CONTENT_TYPES.get(ext, "application/octet-stream"))
        outcome.images.append(
            {"storage_path": storage_path, "original_filename": relative_path}
        )

    # ─── MinIO 辅助 ───

    @staticmethod
    def _storage_path(system_id: UUID, relative_path: str) -> str:
        return f"systems/{system_id}/documents/{relative_path}"

    @staticmethod
    def _put(storage_path: str, data: bytes, content_type: str) -> None:
        minio_client.put_object(
            bucket_name=settings.minio_bucket,
            object_name=storage_path,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
