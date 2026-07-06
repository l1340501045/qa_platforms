"""图覆盖体检 CLI 单测：验证图覆盖率计算逻辑。"""

import pytest

from src.knowledge_base.cli.image_coverage_probe import (
    ImageCoverageReport,
    compute_image_coverage,
)


def test_baseline_zero_coverage():
    """Chunk 0 基线：9 张 md 引用、57 张 MinIO 实有、0 张已描述 → 覆盖率 0%"""
    image_refs = [f"images/img-{i}.png" for i in range(9)]
    minio_objects = [f"systems/xxx/documents/images/img-{i}.png" for i in range(57)]
    image_captions = None  # Chunk 1 前无此列

    report = compute_image_coverage(
        image_refs=image_refs,
        minio_objects=minio_objects,
        image_captions=image_captions,
    )

    assert isinstance(report, ImageCoverageReport)
    assert report.md_referenced == 9
    assert report.minio_total == 57
    assert report.captioned == 0
    assert report.coverage == 0.0


def test_partial_coverage():
    """部分图已有描述（模拟 Chunk 1 后状态）"""
    image_refs = [f"images/img-{i}.png" for i in range(9)]
    minio_objects = [f"prefix/img-{i}.png" for i in range(57)]
    image_captions = {f"img-{i}.png": {"caption_text": "xxx"} for i in range(30)}

    report = compute_image_coverage(
        image_refs=image_refs,
        minio_objects=minio_objects,
        image_captions=image_captions,
    )

    assert report.md_referenced == 9
    assert report.minio_total == 57
    assert report.captioned == 30
    assert abs(report.coverage - 30 / 57) < 0.001


def test_full_coverage():
    """全部描述完 → 覆盖率 100%"""
    image_refs = [f"images/img-{i}.png" for i in range(9)]
    minio_objects = [f"prefix/img-{i}.png" for i in range(57)]
    image_captions = {f"img-{i}.png": {"caption_text": "xxx"} for i in range(57)}

    report = compute_image_coverage(
        image_refs=image_refs,
        minio_objects=minio_objects,
        image_captions=image_captions,
    )

    assert report.captioned == 57
    assert report.coverage == 1.0


def test_empty_minio_zero_division():
    """MinIO 无图 → 覆盖率定义为 0（避免除零）"""
    report = compute_image_coverage(
        image_refs=[],
        minio_objects=[],
        image_captions=None,
    )
    assert report.minio_total == 0
    assert report.coverage == 0.0
