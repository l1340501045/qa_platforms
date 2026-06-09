"""MinIO 存储服务 — 图片上传与 URL 生成"""

import io
import logging
from pathlib import PurePosixPath

from minio import Minio
from minio.error import S3Error

from src.knowledge_base.config import kb_settings

logger = logging.getLogger(__name__)


class MinIOService:
    """MinIO 对象存储交互"""

    def __init__(self) -> None:
        self._client = Minio(
            endpoint=kb_settings.minio_endpoint,
            access_key=kb_settings.minio_access_key,
            secret_key=kb_settings.minio_secret_key,
            secure=kb_settings.minio_secure,
        )
        self._bucket = kb_settings.minio_bucket

    def _ensure_bucket(self) -> None:
        """确保 bucket 存在"""
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def upload_image(self, object_path: str, data: bytes, content_type: str = "image/png") -> str:
        """上传图片到 MinIO，返回对象路径"""
        self._ensure_bucket()
        stream = io.BytesIO(data)
        self._client.put_object(
            bucket_name=self._bucket,
            object_name=object_path,
            data=stream,
            length=len(data),
            content_type=content_type,
        )
        logger.info("Uploaded image to MinIO: %s/%s", self._bucket, object_path)
        return f"{self._bucket}/{object_path}"

    def get_presigned_url(self, object_path: str, expires_hours: int = 24) -> str:
        """生成预签名下载 URL"""
        from datetime import timedelta

        return self._client.presigned_get_object(
            bucket_name=self._bucket,
            object_name=object_path,
            expires=timedelta(hours=expires_hours),
        )

    def delete_object(self, object_path: str) -> None:
        """删除对象"""
        try:
            self._client.remove_object(self._bucket, object_path)
        except S3Error as e:
            logger.warning("Failed to delete MinIO object %s: %s", object_path, e)

    def build_object_path(self, document_id: str, filename: str) -> str:
        """构建标准对象路径: documents/{doc_id}/images/{filename}"""
        return str(PurePosixPath("documents", document_id, "images", filename))
