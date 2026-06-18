"""图清单收集器 — 从 MinIO 取全集图片，合并 image_refs 去重，标注归属。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass
class ImageRef:
    """单张图片的元信息"""

    object_key: str
    filename: str
    referenced_in_md: bool
    section_hint: str | None


_SECTION_HINT_RE = re.compile(
    r"-([A-Z]\d[a-z]?|[A-Z]\d|[Ff]\d+[a-z]?|\d+\.\d+\.\d+|\d+)-",
)


def _parse_section_hint(filename: str) -> str | None:
    """从文件名中提取章节编号前缀。

    匹配模式：PRD名-{编号}-描述.png
    编号示例：80, F1, F1b, 5.8.4, 10
    """
    m = _SECTION_HINT_RE.search(filename)
    return m.group(1) if m else None


def collect_images(
    *,
    system_id: str,
    folder_path: str | None,
    image_refs: list[str] | None,
    minio_objects: list,
) -> list[ImageRef]:
    """收集文档全部图片（MinIO 全集），标注 md 引用状态 + 章节 hint。

    Args:
        system_id: 系统 ID
        folder_path: 文档 folder_path（相对路径前缀）
        image_refs: document.image_refs（md ![]() 引用的相对路径列表）
        minio_objects: minio list_objects 返回的对象列表（需有 .object_name 属性）

    Returns:
        去重后的 ImageRef 列表（按 object_key 去重）
    """
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}

    # 构建 image_refs 的文件名集合（用于标注 referenced_in_md）
    ref_filenames: set[str] = set()
    if image_refs:
        for ref_path in image_refs:
            ref_filenames.add(PurePosixPath(ref_path).name)

    seen_keys: set[str] = set()
    result: list[ImageRef] = []

    for obj in minio_objects:
        key = obj.object_name
        if getattr(obj, "is_dir", False):
            continue
        ext = PurePosixPath(key).suffix.lower()
        if ext not in image_exts:
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)

        filename = PurePosixPath(key).name
        result.append(
            ImageRef(
                object_key=key,
                filename=filename,
                referenced_in_md=filename in ref_filenames,
                section_hint=_parse_section_hint(filename),
            )
        )

    return result
