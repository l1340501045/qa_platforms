"""T042: 落库服务 — 确认后写入正式 test_cases 表 + 自动关联"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID

import yaml
from sqlalchemy import select, update

from src.testcase_generator.db import async_session_factory
from src.platform_api.models.testcase import TestBatch, TestCase
from src.platform_api.models.knowledge import Document
from src.platform_api.models.enums import BatchStatus, ReviewStatus, DocType
from src.knowledge_base.services.linkage_service import LinkageService

logger = logging.getLogger(__name__)


class PersistService:
    """用例落库服务

    确认后将 AI 生成的用例归档，并沉淀为 knowledge.documents 行建立显式关联。
    """

    async def archive_batch(self, batch_id: UUID) -> None:
        """归档批次 — 确认后落库 + 知识沉淀 + 关联

        流程：
        1. 检查所有用例 review_status = confirmed
        2. 将用例集序列化为 YAML 沉淀到 knowledge.documents（doc_type=test_case）
        3. 调用 LinkageService.link_testcase_to_requirement() 建立 需求文档→用例文档 关联
        4. 更新 batch status → archived

        Raises:
            ValueError: 批次不存在或状态不允许归档
            RuntimeError: 存在未确认的用例
        """
        async with async_session_factory() as session:
            # 加载 batch
            batch_stmt = select(TestBatch).where(TestBatch.id == batch_id)
            batch_result = await session.execute(batch_stmt)
            batch = batch_result.scalar_one_or_none()

            if batch is None:
                raise ValueError(f"Batch {batch_id} not found")

            if batch.status not in (
                BatchStatus.PENDING_REVIEW,
                BatchStatus.REVIEWING,
                BatchStatus.COMPLETED,
            ):
                raise ValueError(f"Batch {batch_id} is in status '{batch.status}', cannot archive from this state")

            # 1. 检查所有活跃用例的 review_status
            cases_stmt = select(TestCase).where(
                TestCase.batch_id == batch_id,
                TestCase.review_status != ReviewStatus.DELETED,
            )
            cases_result = await session.execute(cases_stmt)
            cases = list(cases_result.scalars().all())

            unconfirmed = [c for c in cases if c.review_status != ReviewStatus.CONFIRMED]
            if unconfirmed:
                unconfirmed_ids = [str(c.id) for c in unconfirmed[:10]]
                raise RuntimeError(
                    f"Cannot archive: {len(unconfirmed)} cases are not confirmed. First few: {unconfirmed_ids}"
                )

            # 2. 将用例集沉淀为 knowledge.documents（doc_type=test_case）
            cases_yaml = yaml.dump(
                [
                    {
                        "id": str(c.id),
                        "title": c.title,
                        "priority": c.priority,
                        "preconditions": c.preconditions,
                        "steps": c.steps,
                        "expected_results": c.expected_results,
                        "dimensions": c.dimensions,
                    }
                    for c in cases
                ],
                allow_unicode=True,
                default_flow_style=False,
            )

            content_hash = hashlib.sha256(cases_yaml.encode()).hexdigest()

            test_case_doc = Document(
                id=uuid.uuid4(),
                system_id=batch.system_id,
                title=f"AI 生成用例集 — 批次 {batch_id}",
                doc_type=DocType.TEST_CASE,
                trust_level=3,  # AI 生成，经人工确认
                content=cases_yaml,
                storage_path=f"testcase/batch_{batch_id}.yaml",
                content_hash=content_hash,
                embedding_status="pending",
            )
            session.add(test_case_doc)
            await session.flush()  # 确保 doc ID 可用

            # 3. 建立 需求文档 → 用例文档 关联
            requirement_doc_id = batch.document_id
            linkage_service = LinkageService(session)
            await linkage_service.link_testcase_to_requirement(
                requirement_doc_id=requirement_doc_id,
                test_case_doc_id=test_case_doc.id,
            )

            # 4. 更新 batch status → archived
            archive_stmt = update(TestBatch).where(TestBatch.id == batch_id).values(status=BatchStatus.ARCHIVED)
            await session.execute(archive_stmt)
            await session.commit()

        logger.info(
            "Batch %s archived: %d cases confirmed, knowledge doc %s created",
            batch_id,
            len(cases),
            test_case_doc.id,
        )
