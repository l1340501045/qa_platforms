"""T016: 信源注册表 — 管理和排序所有信息来源"""

from __future__ import annotations

from uuid import UUID

from src.platform_api.models.enums import DocType
from src.testcase_generator.schemas.parsed_context import SourceItem, SectionExtract


class SourceRegistry:
    """信源注册表：收集所有信源，按信任等级排序，标注来源引用

    信任等级越低数值越小，优先级越高（1=最高权威，5=最低）。
    """

    def __init__(self) -> None:
        self._sources: list[SourceItem] = []

    def register_source(
        self,
        doc_id: UUID,
        doc_type: str | DocType,
        trust_level: int,
        title: str,
        sections: list[SectionExtract] | None = None,
    ) -> SourceItem:
        """注册一个信源文档

        Args:
            doc_id: 文档 UUID
            doc_type: 文档类型（使用 DocType 枚举值）
            trust_level: 信任等级 1-5
            title: 文档标题
            sections: 提取的章节列表

        Returns:
            注册后的 SourceItem
        """
        source = SourceItem(
            doc_id=doc_id,
            doc_type=str(doc_type),
            trust_level=trust_level,
            title=title,
            sections=sections or [],
        )
        self._sources.append(source)
        return source

    def get_sorted_sources(self) -> list[SourceItem]:
        """按信任等级升序排序（1=最高优先）"""
        return sorted(self._sources, key=lambda s: s.trust_level)

    def get_by_trust_level(self, level: int) -> list[SourceItem]:
        """获取指定信任等级的所有信源"""
        return [s for s in self._sources if s.trust_level == level]

    @property
    def sources(self) -> list[SourceItem]:
        """返回所有已注册信源（未排序）"""
        return list(self._sources)

    @property
    def count(self) -> int:
        return len(self._sources)
