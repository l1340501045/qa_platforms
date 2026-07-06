"""图清单收集器测试：合并 MinIO 全集 + image_refs，去重，标注归属"""

import pytest

from src.knowledge_base.services.image_caption.image_collector import (
    ImageRef,
    collect_images,
)


def _mock_minio_object(name: str):
    """模拟 minio list_objects 返回的对象"""

    class FakeObj:
        def __init__(self, object_name):
            self.object_name = object_name
            self.is_dir = False

    return FakeObj(name)


class TestCollectImages:
    def test_merges_minio_and_image_refs_deduped(self):
        """MinIO 57 张 + image_refs 9 张（含重叠）→ 合并去重得 57 项"""
        system_id = "sys-001"
        folder_path = "漫剧批创初版功能PRD"

        # image_refs 里 9 项（相对路径）
        image_refs = [f"images/漫剧批创初版功能PRD-{i:02d}-desc.png" for i in range(9)]

        # MinIO 返回 57 项（含 image_refs 的 9 项 + 48 项额外）
        prefix = f"systems/{system_id}/documents/{folder_path}/"
        minio_objects = [
            _mock_minio_object(f"{prefix}images/漫剧批创初版功能PRD-{i:02d}-desc.png")
            for i in range(57)
        ]

        result = collect_images(
            system_id=system_id,
            folder_path=folder_path,
            image_refs=image_refs,
            minio_objects=minio_objects,
        )

        assert len(result) == 57
        assert all(isinstance(r, ImageRef) for r in result)

    def test_referenced_in_md_marked_correctly(self):
        """image_refs 中的图标记 referenced_in_md=True"""
        system_id = "sys-001"
        folder_path = "prd"
        image_refs = ["images/img-01.png", "images/img-02.png"]

        prefix = f"systems/{system_id}/documents/{folder_path}/"
        minio_objects = [
            _mock_minio_object(f"{prefix}images/img-{i:02d}.png")
            for i in range(1, 6)
        ]

        result = collect_images(
            system_id=system_id,
            folder_path=folder_path,
            image_refs=image_refs,
            minio_objects=minio_objects,
        )

        ref_map = {r.filename: r.referenced_in_md for r in result}
        assert ref_map["img-01.png"] is True
        assert ref_map["img-02.png"] is True
        assert ref_map["img-03.png"] is False
        assert ref_map["img-04.png"] is False

    def test_section_hint_parsed_from_filename(self):
        """文件名编号前缀被解析为 section_hint"""
        system_id = "sys-001"
        folder_path = "prd"
        prefix = f"systems/{system_id}/documents/{folder_path}/"

        minio_objects = [
            _mock_minio_object(f"{prefix}images/漫剧批创初版功能PRD-80-batch-create.png"),
            _mock_minio_object(f"{prefix}images/漫剧批创初版功能PRD-F1-auth-flow.png"),
            _mock_minio_object(f"{prefix}images/漫剧批创初版功能PRD-5.8.4-detail.png"),
            _mock_minio_object(f"{prefix}images/random-image.png"),
        ]

        result = collect_images(
            system_id=system_id,
            folder_path=folder_path,
            image_refs=[],
            minio_objects=minio_objects,
        )

        hint_map = {r.filename: r.section_hint for r in result}
        assert hint_map["漫剧批创初版功能PRD-80-batch-create.png"] == "80"
        assert hint_map["漫剧批创初版功能PRD-F1-auth-flow.png"] == "F1"
        assert hint_map["漫剧批创初版功能PRD-5.8.4-detail.png"] == "5.8.4"
        assert hint_map["random-image.png"] is None

    def test_empty_minio_returns_empty(self):
        """MinIO 无图 → 空列表"""
        result = collect_images(
            system_id="sys-001",
            folder_path="prd",
            image_refs=["images/x.png"],
            minio_objects=[],
        )
        assert result == []
