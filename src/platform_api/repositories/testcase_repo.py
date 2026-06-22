"""用例仓库 — 用例树聚合查询、全文搜索、steps_text 计算"""

from uuid import UUID

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.knowledge import Document
from src.platform_api.models.public import System
from src.platform_api.models.testcase import TestBatch, TestCase
from src.platform_api.repositories.base import BaseRepository


def compute_steps_text(title: str, steps: list[dict]) -> str:
    """
    计算 steps_text 索引值：title + 所有 step.action 拼接

    在应用层 INSERT/UPDATE 时调用，保持与 009 回填迁移一致的逻辑。
    """
    actions = [s.get("action", "") for s in steps if s.get("action")]
    return title + " " + " ".join(actions)


class TestCaseRepository(BaseRepository[TestCase]):
    """用例数据仓库"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, TestCase)

    async def query_tree_data(
        self,
        batch_ids: list[UUID],
        priority: str | None = None,
        review_status: str | None = None,
    ) -> list[dict]:
        """
        用例树聚合数据查询

        返回指定批次下的用例列表（含 document 信息），Service 层负责内存分组。

        Args:
            batch_ids: 批次 ID 列表（通常为各文档最新完成批次）
            priority: 优先级筛选
            review_status: review 状态筛选
        """
        stmt = (
            select(
                TestCase.id,
                TestCase.title,
                TestCase.priority,
                TestCase.trust_level,
                TestCase.review_status,
                TestCase.iteration,
                TestCase.provenance,
                TestCase.batch_id,
                TestBatch.document_id,
                Document.title.label("document_title"),
            )
            .join(TestBatch, TestCase.batch_id == TestBatch.id)
            .join(Document, TestBatch.document_id == Document.id)
            .where(TestCase.batch_id.in_(batch_ids))
            .where(TestCase.review_status != "deleted")
        )

        if priority is not None:
            stmt = stmt.where(TestCase.priority == priority)
        if review_status is not None:
            stmt = stmt.where(TestCase.review_status == review_status)

        stmt = stmt.order_by(Document.title, TestCase.title)

        result = await self.session.execute(stmt)
        return [row._asdict() for row in result.all()]

    async def search_by_text(
        self,
        query: str,
        system_id: UUID | None = None,
        priority: str | None = None,
        review_status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[dict], int]:
        """
        全局搜索用例（基于 pg_trgm word_similarity）

        word_similarity(query, text) 衡量查询词与文本中最佳匹配片段的相似度，
        不受目标文本总长度影响，适合短关键词搜索长文本场景。
        GIN gin_trgm_ops 索引同时支持 word_similarity 算子，无需额外索引。

        Args:
            query: 搜索关键词
            system_id: 限定系统范围
            priority: 优先级筛选
            review_status: review 状态筛选
            page/per_page: 分页参数

        Returns:
            tuple[list[dict], int]: (搜索结果列表, 总数)
        """
        # word_similarity：查询词 vs 文本最佳匹配片段，与文本总长无关
        similarity = func.word_similarity(query, TestCase.steps_text)

        # 基础查询
        base_query = (
            select(
                TestCase.id,
                TestCase.title,
                TestCase.priority,
                TestCase.trust_level,
                TestCase.review_status,
                TestBatch.system_id,
                System.name.label("system_name"),
                TestBatch.document_id.label("document_id"),
                Document.title.label("document_title"),
                TestCase.batch_id,
                similarity.label("score"),
                TestCase.created_at,
            )
            .join(TestBatch, TestCase.batch_id == TestBatch.id)
            .join(Document, TestBatch.document_id == Document.id)
            .join(System, TestBatch.system_id == System.id)
            .where(TestCase.steps_text.isnot(None))
            .where(similarity > 0.4)  # word_similarity 阈值：减少弱匹配噪声
            .where(TestCase.review_status != "deleted")
        )

        # 筛选条件
        if system_id is not None:
            base_query = base_query.where(TestBatch.system_id == system_id)
        if priority is not None:
            base_query = base_query.where(TestCase.priority == priority)
        if review_status is not None:
            base_query = base_query.where(TestCase.review_status == review_status)

        # 计数查询（用子查询）
        count_subq = base_query.subquery()
        count_query = select(func.count()).select_from(count_subq)

        # 排序 + 分页
        base_query = base_query.order_by(similarity.desc())
        offset = (page - 1) * per_page
        base_query = base_query.offset(offset).limit(per_page)

        # 执行
        result = await self.session.execute(base_query)
        items = [row._asdict() for row in result.all()]

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return items, total
