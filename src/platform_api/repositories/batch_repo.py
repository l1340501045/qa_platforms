"""批次仓库 — 批次列表查询、选项、状态更新"""

from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.knowledge import Document
from src.platform_api.models.public import System
from src.platform_api.models.testcase import TestBatch
from src.platform_api.repositories.base import BaseRepository


class BatchRepository(BaseRepository[TestBatch]):
    """批次数据仓库"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, TestBatch)

    async def find_by_system(
        self,
        system_id: UUID,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict], int]:
        """
        查询系统下的批次列表（关联 document_title）

        Returns:
            tuple[list[dict], int]: (批次列表含 document_title, 总数)
        """
        # 基础查询
        base_query = (
            select(
                TestBatch.id,
                TestBatch.document_id,
                Document.title.label("document_title"),
                TestBatch.status,
                TestBatch.total_cases,
                TestBatch.started_at,
                TestBatch.completed_at,
                TestBatch.created_at,
            )
            .join(Document, TestBatch.document_id == Document.id)
            .where(TestBatch.system_id == system_id)
        )

        count_query = select(func.count()).select_from(TestBatch).where(TestBatch.system_id == system_id)

        if status is not None:
            base_query = base_query.where(TestBatch.status == status)
            count_query = count_query.where(TestBatch.status == status)

        # 排序：最新的在前
        base_query = base_query.order_by(TestBatch.created_at.desc())

        # 分页
        offset = (page - 1) * per_page
        base_query = base_query.offset(offset).limit(per_page)

        # 执行
        result = await self.session.execute(base_query)
        items = [row._asdict() for row in result.all()]

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return items, total

    async def find_by_document(
        self,
        document_id: UUID,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict], int]:
        """
        查询文档下的批次列表

        Returns:
            tuple[list[dict], int]: (批次列表含 document_title, 总数)
        """
        base_query = (
            select(
                TestBatch.id,
                TestBatch.document_id,
                Document.title.label("document_title"),
                TestBatch.status,
                TestBatch.total_cases,
                TestBatch.started_at,
                TestBatch.completed_at,
                TestBatch.created_at,
            )
            .join(Document, TestBatch.document_id == Document.id)
            .where(TestBatch.document_id == document_id)
        )

        count_query = select(func.count()).select_from(TestBatch).where(TestBatch.document_id == document_id)

        if status is not None:
            base_query = base_query.where(TestBatch.status == status)
            count_query = count_query.where(TestBatch.status == status)

        base_query = base_query.order_by(TestBatch.created_at.desc())

        offset = (page - 1) * per_page
        base_query = base_query.offset(offset).limit(per_page)

        result = await self.session.execute(base_query)
        items = [row._asdict() for row in result.all()]

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return items, total

    async def find_latest_viewable_per_document(self, system_id: UUID) -> list[dict]:
        """
        获取系统下每个文档的最新可见批次（DISTINCT ON document_id）

        可见批次状态：pending_review（待人工评审）、completed、archived。
        用于用例树默认聚合：未指定 batch_id 时，取各文档最新可见批次。

        注：AI 生成流水线终点是 pending_review，此时用例已生成完毕可供浏览；
        不包含 running/pending/failed/suspended 等中间/异常态。
        """
        stmt = (
            select(
                TestBatch.id,
                TestBatch.document_id,
                TestBatch.status,
                TestBatch.created_at,
            )
            .where(
                and_(
                    TestBatch.system_id == system_id,
                    TestBatch.status.in_(["pending_review", "completed", "archived"]),
                )
            )
            .distinct(TestBatch.document_id)
            .order_by(TestBatch.document_id, TestBatch.created_at.desc())
        )

        result = await self.session.execute(stmt)
        return [row._asdict() for row in result.all()]

    async def find_options(self) -> list[dict]:
        """
        获取可导出的批次选项列表（status 为 completed 或 archived）

        用于前端批次下拉选择器。
        """
        stmt = (
            select(
                TestBatch.id,
                Document.title.label("document_title"),
                TestBatch.status,
                TestBatch.created_at,
                System.name.label("system_name"),
            )
            .join(Document, TestBatch.document_id == Document.id)
            .join(System, TestBatch.system_id == System.id)
            .where(TestBatch.status.in_(["completed", "archived"]))
            .order_by(TestBatch.created_at.desc())
        )

        result = await self.session.execute(stmt)
        return [row._asdict() for row in result.all()]

    async def find_all(
        self,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict], int]:
        """
        全局批次列表（跨系统），关联 document_title + system_name

        Returns:
            tuple[list[dict], int]: (批次列表, 总数)
        """
        base_query = (
            select(
                TestBatch.id,
                TestBatch.document_id,
                Document.title.label("document_title"),
                TestBatch.system_id,
                System.name.label("system_name"),
                TestBatch.status,
                TestBatch.total_cases,
                TestBatch.started_at,
                TestBatch.completed_at,
                TestBatch.created_at,
            )
            .join(Document, TestBatch.document_id == Document.id)
            .join(System, TestBatch.system_id == System.id)
        )

        count_query = select(func.count()).select_from(TestBatch)

        if status is not None:
            base_query = base_query.where(TestBatch.status == status)
            count_query = count_query.where(TestBatch.status == status)

        base_query = base_query.order_by(TestBatch.created_at.desc())

        offset = (page - 1) * per_page
        base_query = base_query.offset(offset).limit(per_page)

        result = await self.session.execute(base_query)
        items = [row._asdict() for row in result.all()]

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return items, total

    async def update_status(self, batch_id: UUID, status: str) -> TestBatch | None:
        """更新批次状态"""
        return await self.update(batch_id, status=status)
