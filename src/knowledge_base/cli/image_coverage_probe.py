"""图覆盖体检 CLI — 量化 PRD 图片被解析的比例。

用法：
    uv run python -m src.knowledge_base.cli.image_coverage_probe --document-id <uuid>
    uv run python -m src.knowledge_base.cli.image_coverage_probe --system-id <uuid>

输出：md_referenced / minio_total / captioned / coverage
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ImageCoverageReport:
    """图覆盖体检结果"""

    md_referenced: int
    minio_total: int
    captioned: int
    coverage: float


def compute_image_coverage(
    *,
    image_refs: list,
    minio_objects: list[str],
    image_captions: dict | None,
) -> ImageCoverageReport:
    """纯计算逻辑：统计 md 引用数、MinIO 实有数、已描述数、覆盖率。

    - image_refs: document.image_refs（md 正文 ![]() 引用的图路径列表）
    - minio_objects: MinIO 目录下所有图片对象的 key 列表（全集）
    - image_captions: document.image_captions（已描述的图 dict，Chunk 1 前为 None）
    """
    md_referenced = len(image_refs) if image_refs else 0
    minio_total = len(minio_objects)
    captioned = len(image_captions) if image_captions else 0
    coverage = captioned / minio_total if minio_total > 0 else 0.0

    return ImageCoverageReport(
        md_referenced=md_referenced,
        minio_total=minio_total,
        captioned=captioned,
        coverage=coverage,
    )


async def _run_probe(document_id: str | None, system_id: str | None) -> None:
    """实际执行：查 DB + 列 MinIO + 计算覆盖率"""
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.knowledge_base.db import async_session_factory
    from src.platform_api.core.settings import settings
    from src.platform_api.models.knowledge import Document

    try:
        from minio import Minio
    except ImportError:
        print("ERROR: minio package not installed", file=sys.stderr)
        sys.exit(1)

    async with async_session_factory() as session:
        session: AsyncSession
        if document_id:
            stmt = select(Document).where(Document.id == UUID(document_id))
        else:
            stmt = select(Document).where(
                Document.system_id == UUID(system_id),
                Document.deleted_at.is_(None),
            )
        result = await session.execute(stmt)
        documents = result.scalars().all()

    if not documents:
        print("ERROR: 未找到文档", file=sys.stderr)
        sys.exit(1)

    minio_client = Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )

    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}

    for doc in documents:
        prefix = f"systems/{doc.system_id}/documents/"
        if doc.folder_path:
            prefix = f"systems/{doc.system_id}/documents/{doc.folder_path}/"

        objects = minio_client.list_objects(
            settings.minio_bucket, prefix=prefix, recursive=True
        )
        minio_images = [
            obj.object_name
            for obj in objects
            if any(obj.object_name.lower().endswith(ext) for ext in image_exts)
        ]

        image_captions = getattr(doc, "image_captions", None)

        report = compute_image_coverage(
            image_refs=doc.image_refs or [],
            minio_objects=minio_images,
            image_captions=image_captions,
        )

        print(f"── 文档: {doc.title} ({doc.id}) ──")
        print(f"  md 引用图数:   {report.md_referenced}")
        print(f"  MinIO 实有图:  {report.minio_total}")
        print(f"  已描述图数:    {report.captioned}")
        print(f"  覆盖率:        {report.coverage:.1%}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="图覆盖体检")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--document-id", help="文档 UUID")
    group.add_argument("--system-id", help="系统 UUID（检查该系统下所有文档）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run_probe(args.document_id, args.system_id))


if __name__ == "__main__":
    main()
