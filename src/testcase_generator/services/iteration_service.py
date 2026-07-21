"""T041: Review 迭代 — 基于人工反馈重跑 write-cases"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from src.platform_api.models.enums import BatchStatus, ReviewStatus
from src.platform_api.models.testcase import TestBatch, TestCase, TestPoint
from src.testcase_generator.db import async_session_factory

logger = logging.getLogger(__name__)


class IterationService:
    """基于人工反馈的迭代重生成服务

    在 review 阶段，QA 人员可标记需要修改的用例，
    系统仅对这些用例关联的 test_points 重跑 write-cases + review。
    """

    async def iterate(
        self,
        batch_id: UUID,
        modified_case_ids: list[str],
        feedback: dict,
    ) -> list[dict[str, Any]]:
        """基于人工反馈重跑部分用例生成

        Args:
            batch_id: 批次 ID
            modified_case_ids: 需要重新生成的用例 ID 列表
            feedback: 人工反馈信息 {"comments": ..., "modification_hints": ...}

        Returns:
            合并后的最终用例列表（未修改的保留 + 重新生成的替换）
        """
        requested_case_ids = {uuid.UUID(case_id) for case_id in modified_case_ids}
        if not requested_case_ids:
            raise ValueError("At least one case must be selected for iteration")
        async with async_session_factory() as session:
            # 1. 读取 batch 信息，验证状态
            batch_stmt = select(TestBatch).where(TestBatch.id == batch_id).with_for_update()
            batch_result = await session.execute(batch_stmt)
            batch = batch_result.scalar_one_or_none()

            if batch is None:
                raise ValueError(f"Batch {batch_id} not found")

            if batch.status != BatchStatus.PENDING_REVIEW:
                raise ValueError(f"Batch {batch_id} is in status '{batch.status}', expected 'pending_review'")
            if batch.taxonomy_version_id is not None:
                raise ValueError(f"Batch {batch_id} taxonomy is frozen and cannot iterate")

            # 2. 筛选 modified_case_ids 对应的 test_point_ids
            cases_stmt = select(TestCase).where(
                TestCase.batch_id == batch_id,
                TestCase.id.in_(requested_case_ids),
            )
            cases_result = await session.execute(cases_stmt)
            modified_cases = list(cases_result.scalars().all())
            found_case_ids = {case.id for case in modified_cases}
            if found_case_ids != requested_case_ids:
                missing = sorted(str(case_id) for case_id in requested_case_ids - found_case_ids)
                raise ValueError(f"Cases do not all belong to batch {batch_id}: missing={missing[:5]}")

            test_point_ids = {c.test_point_id for c in modified_cases if c.test_point_id is not None}

            # 从库中读取各用例的 review_comment 组成 feedback（修复：前端传入的 feedback 为空时兜底）
            if not feedback:
                feedback = {}
            for case in modified_cases:
                if case.review_comment and str(case.id) not in feedback:
                    feedback[str(case.id)] = case.review_comment

            # 3. 加载需要重跑的 test_points
            if test_point_ids:
                tp_stmt = select(TestPoint).where(TestPoint.id.in_(test_point_ids))
                tp_result = await session.execute(tp_stmt)
                target_test_points = list(tp_result.scalars().all())
            else:
                target_test_points = []

            # 4. 加载所有现有用例（用于合并）
            all_cases_stmt = select(TestCase).where(TestCase.batch_id == batch_id)
            all_cases_result = await session.execute(all_cases_stmt)
            all_cases = list(all_cases_result.scalars().all())

            # 更新 batch 状态为 reviewing
            batch.status = BatchStatus.REVIEWING
            await session.commit()

        try:
            # 5. 仅对目标 test_points 重跑 write-cases 阶段
            regenerated_cases = await self._rerun_write_cases(
                batch_id=str(batch_id),
                system_id=str(batch.system_id),
                test_points=target_test_points,
                feedback=feedback,
            )

            # 6. 合并结果
            merged_cases: list[dict[str, Any]] = []

            # 保留未修改的
            for case in all_cases:
                if case.id not in requested_case_ids:
                    merged_cases.append(
                        {
                            "id": str(case.id),
                            "test_point_id": str(case.test_point_id) if case.test_point_id else None,
                            "title": case.title,
                            "preconditions": case.preconditions,
                            "steps": case.steps,
                            "expected_results": case.expected_results,
                            "priority": case.priority,
                            "dimensions": case.dimensions,
                            "provenance": case.provenance,
                            "trust_level": case.trust_level,
                            "confidence_note": case.confidence_note,
                        }
                    )

            # 加入重新生成的
            merged_cases.extend(regenerated_cases)

            # 7. 更新数据库中的用例
            async with async_session_factory() as session:
                locked_batch = (
                    await session.execute(select(TestBatch).where(TestBatch.id == batch_id).with_for_update())
                ).scalar_one_or_none()
                if locked_batch is None:
                    raise ValueError(f"Batch {batch_id} not found")
                if locked_batch.status != BatchStatus.REVIEWING or locked_batch.taxonomy_version_id is not None:
                    raise ValueError(f"Batch {batch_id} changed while iteration was running")

                # 删除旧的被修改的用例
                await session.execute(
                    update(TestCase)
                    .where(
                        TestCase.batch_id == batch_id,
                        TestCase.id.in_(requested_case_ids),
                    )
                    .values(review_status=ReviewStatus.DELETED)
                )

                # 写入重新生成的用例
                current_iteration = (batch.generation_config or {}).get("iteration", 1) + 1
                for case_data in regenerated_cases:
                    new_case = TestCase(
                        id=uuid.uuid4(),
                        batch_id=batch_id,
                        test_point_id=(
                            uuid.UUID(case_data["test_point_id"]) if case_data.get("test_point_id") else None
                        ),
                        title=case_data.get("title", ""),
                        preconditions=case_data.get("preconditions", []),
                        steps=case_data.get("steps", []),
                        expected_results=case_data.get("expected_results", []),
                        priority=case_data.get("priority", "P2"),
                        dimensions=case_data.get("dimensions", []),
                        provenance=case_data.get("provenance", {}),
                        trust_level=case_data.get("trust_level", 3),
                        confidence_note=case_data.get("confidence_note"),
                        review_status=ReviewStatus.PENDING,
                        iteration=current_iteration,
                    )
                    session.add(new_case)

                # 更新 batch 状态回 pending_review
                locked_batch.status = BatchStatus.PENDING_REVIEW
                await session.commit()
        except Exception:
            try:
                await self._release_failed_iteration(batch_id)
            except Exception:
                logger.exception("Failed to release iteration claim for batch %s", batch_id)
            raise

        logger.info(
            "Iteration completed for batch %s: %d cases regenerated, %d total",
            batch_id,
            len(regenerated_cases),
            len(merged_cases),
        )

        return merged_cases

    async def _release_failed_iteration(self, batch_id: UUID) -> None:
        """普通异常后释放本次状态占用；进程崩溃仍需运维按日志恢复。"""
        async with async_session_factory() as session:
            batch = (
                await session.execute(select(TestBatch).where(TestBatch.id == batch_id).with_for_update())
            ).scalar_one_or_none()
            if batch is not None and batch.status == BatchStatus.REVIEWING and batch.taxonomy_version_id is None:
                batch.status = BatchStatus.PENDING_REVIEW
                await session.commit()

    async def _rerun_write_cases(
        self,
        batch_id: str,
        system_id: str,
        test_points: list,
        feedback: dict,
    ) -> list[dict[str, Any]]:
        """仅重跑 write-cases 阶段

        构建一个局部 PipelineState，只包含需要重写的 test_points，
        通过 LangGraph 编译的子图执行 write_cases 节点。
        """
        from src.testcase_generator.schemas.test_point import TestPointSchema
        from src.testcase_generator.stages.write_cases.node import write_cases_node

        # 将 ORM 模型转换为 schema
        tp_schemas = []
        for tp in test_points:
            tp_schema = TestPointSchema(
                id=tp.feature_id,
                feature_id=tp.feature_id,
                dimension=tp.dimension,
                description=tp.description,
                priority=tp.priority,
                derived_from=tp.derived_from if isinstance(tp.derived_from, list) else [],
            )
            tp_schemas.append(tp_schema)

        # 构建局部状态
        partial_state = {
            "document_id": "",
            "system_id": system_id,
            "batch_id": batch_id,
            "generation_config": {"feedback": feedback},
            "test_points": tp_schemas,
        }

        # 直接调用 write_cases_node
        result = await write_cases_node(partial_state)

        # 提取生成的用例
        generated = result.get("test_cases", [])
        return [c.model_dump() if hasattr(c, "model_dump") else c for c in generated]
