"""T045: Golden-set 评估框架 — 标准集对比 + 自动评分"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID

import yaml
from sqlalchemy import select

from src.testcase_generator.db import async_session_factory
from src.platform_api.models.testcase import (
    GoldenSetResult,
    TestBatch,
    TestCase,
    TestPoint,
)
from src.platform_api.models.enums import BatchStatus

logger = logging.getLogger(__name__)

# golden_set 在 stage_artifacts 中以特定 stage 标识存储
GOLDEN_SET_STAGE = "golden_set"


class GoldenSetEvaluator:
    """Golden-set 评估框架

    对比 AI 生成用例与资深 QA 编写的标准集，
    计算覆盖度、遗漏率、新增价值率等指标。
    """

    async def evaluate(
        self,
        system_id: UUID,
        batch_id: UUID | None = None,
    ) -> dict:
        """评估 AI 生成用例的质量

        流程：
        1. 加载该系统的 golden_set（人写的标准用例）
        2. 加载 AI 生成的最新用例
        3. 对比计算覆盖度指标
        4. 生成 gap_analysis
        5. 写入 golden_set_results 表

        Args:
            system_id: 系统 ID
            batch_id: 可选批次 ID，不指定则取最新完成的批次

        Returns:
            评估报告字典，含各项指标和 gap_analysis
        """
        async with async_session_factory() as session:
            # 1. 加载 golden_set
            golden_cases = await self._load_golden_set(session, system_id)
            if not golden_cases:
                logger.warning("No golden set found for system %s", system_id)
                return {
                    "error": "no_golden_set",
                    "message": f"No golden set imported for system {system_id}",
                }

            # 2. 加载 AI 生成的用例
            ai_cases = await self._load_ai_cases(session, system_id, batch_id)
            if not ai_cases:
                logger.warning("No AI cases found for system %s", system_id)
                return {
                    "error": "no_ai_cases",
                    "message": f"No AI generated cases found for system {system_id}",
                }

            # 3. 对比计算
            golden_points = self._extract_test_points(golden_cases)
            ai_points = self._extract_test_points(ai_cases)

            # 覆盖度计算
            golden_set_descriptions = set(golden_points)
            ai_set_descriptions = set(ai_points)

            overlap = golden_set_descriptions & ai_set_descriptions
            ai_misses = golden_set_descriptions - ai_set_descriptions
            ai_novel = ai_set_descriptions - golden_set_descriptions

            total_golden = len(golden_set_descriptions) or 1  # 避免除零
            total_ai = len(ai_set_descriptions) or 1

            coverage_overlap = len(overlap) / total_golden
            ai_miss_rate = len(ai_misses) / total_golden
            ai_novel_rate = len(ai_novel) / total_ai

            # 直接可用率 = AI 覆盖了 golden 的比例（近似）
            direct_usability_rate = coverage_overlap

            # 4. gap_analysis
            gap_analysis = [{"type": "ai_miss", "description": desc} for desc in sorted(ai_misses)]

            # 5. 写入 golden_set_results 表
            result_record = GoldenSetResult(
                id=uuid.uuid4(),
                batch_id=batch_id,
                golden_set_id=str(system_id),
                kernel_version="1.0",
                coverage_overlap=coverage_overlap,
                ai_miss_rate=ai_miss_rate,
                ai_valuable_addition_rate=ai_novel_rate,
                direct_usability_rate=direct_usability_rate,
                detail_report={
                    "golden_count": len(golden_set_descriptions),
                    "ai_count": len(ai_set_descriptions),
                    "overlap_count": len(overlap),
                    "ai_miss_count": len(ai_misses),
                    "ai_novel_count": len(ai_novel),
                    "gap_analysis": gap_analysis,
                },
                evaluated_at=datetime.now(timezone.utc),
            )
            session.add(result_record)
            await session.commit()

            report = {
                "coverage_overlap": coverage_overlap,
                "ai_miss_rate": ai_miss_rate,
                "ai_novel_rate": ai_novel_rate,
                "direct_usability_rate": direct_usability_rate,
                "golden_count": len(golden_set_descriptions),
                "ai_count": len(ai_set_descriptions),
                "overlap_count": len(overlap),
                "gap_analysis": gap_analysis,
                "result_id": str(result_record.id),
            }

        logger.info(
            "Golden-set evaluation for system %s: coverage=%.2f, miss=%.2f, novel=%.2f",
            system_id,
            coverage_overlap,
            ai_miss_rate,
            ai_novel_rate,
        )
        return report

    async def import_golden_set(
        self,
        system_id: UUID,
        human_cases_yaml: str,
    ) -> int:
        """导入资深 QA 的标准用例作为 golden set

        将人工编写的标准用例 YAML 解析后存储为 golden_set 测试点，
        用于后续评估 AI 生成质量。

        Args:
            system_id: 系统 ID
            human_cases_yaml: YAML 格式的标准用例集

        Returns:
            导入的用例数量
        """
        # 解析 YAML
        try:
            cases_data = yaml.safe_load(human_cases_yaml)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML format: {e}") from e

        if not isinstance(cases_data, list):
            # 尝试从字典中提取列表
            if isinstance(cases_data, dict) and "cases" in cases_data:
                cases_data = cases_data["cases"]
            elif isinstance(cases_data, dict) and "test_cases" in cases_data:
                cases_data = cases_data["test_cases"]
            else:
                raise ValueError("YAML must contain a list of test cases or a dict with 'cases'/'test_cases' key")

        async with async_session_factory() as session:
            # 创建一个特殊的 golden_set batch
            from src.platform_api.models.testcase import StageArtifact

            # 存储为 stage_artifact（golden_set 类型）
            artifact = StageArtifact(
                id=uuid.uuid4(),
                batch_id=None,  # golden_set 不关联特定 batch
                stage=GOLDEN_SET_STAGE,
                status="imported",
                artifact={
                    "system_id": str(system_id),
                    "cases": cases_data,
                    "imported_at": datetime.now(timezone.utc).isoformat(),
                    "total_cases": len(cases_data),
                },
            )

            # StageArtifact 有 batch_id NOT NULL 约束，需要用另一种方式存储
            # 改用 golden_set_results 表的 detail_report 字段存储 golden set 数据
            golden_record = GoldenSetResult(
                id=uuid.uuid4(),
                batch_id=None,
                golden_set_id=f"golden_{system_id}",
                kernel_version="import",
                coverage_overlap=0.0,
                ai_miss_rate=0.0,
                ai_valuable_addition_rate=0.0,
                direct_usability_rate=0.0,
                detail_report={
                    "type": "golden_set_import",
                    "system_id": str(system_id),
                    "cases": cases_data,
                    "imported_at": datetime.now(timezone.utc).isoformat(),
                },
                evaluated_at=datetime.now(timezone.utc),
            )
            session.add(golden_record)
            await session.commit()

        logger.info(
            "Imported %d golden set cases for system %s",
            len(cases_data),
            system_id,
        )
        return len(cases_data)

    async def _load_golden_set(self, session, system_id: UUID) -> list[dict]:
        """加载系统的 golden set 用例"""
        stmt = (
            select(GoldenSetResult)
            .where(
                GoldenSetResult.golden_set_id == f"golden_{system_id}",
                GoldenSetResult.kernel_version == "import",
            )
            .order_by(GoldenSetResult.evaluated_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            return []

        detail = record.detail_report or {}
        return detail.get("cases", [])

    async def _load_ai_cases(self, session, system_id: UUID, batch_id: UUID | None) -> list[dict]:
        """加载 AI 生成的用例"""
        if batch_id:
            # 指定批次
            stmt = select(TestCase).where(TestCase.batch_id == batch_id)
        else:
            # 查最新完成的批次
            batch_stmt = (
                select(TestBatch)
                .where(
                    TestBatch.system_id == system_id,
                    TestBatch.status.in_(
                        [
                            BatchStatus.COMPLETED,
                            BatchStatus.PENDING_REVIEW,
                            BatchStatus.ARCHIVED,
                        ]
                    ),
                )
                .order_by(TestBatch.completed_at.desc())
                .limit(1)
            )
            batch_result = await session.execute(batch_stmt)
            batch = batch_result.scalar_one_or_none()
            if batch is None:
                return []
            stmt = select(TestCase).where(TestCase.batch_id == batch.id)

        result = await session.execute(stmt)
        cases = list(result.scalars().all())

        return [
            {
                "title": c.title,
                "dimensions": c.dimensions,
                "priority": c.priority,
                "steps": c.steps,
                "expected_results": c.expected_results,
            }
            for c in cases
        ]

    def _extract_test_points(self, cases: list[dict]) -> list[str]:
        """从用例列表提取归一化的测试点描述（用于集合对比）

        提取规则：使用 title 作为测试点的唯一标识进行归一化比较。
        实际场景中可结合 embedding 相似度进行模糊匹配。
        """
        points = []
        for case in cases:
            title = case.get("title", "")
            if title:
                # 归一化：去空格、小写
                normalized = title.strip().lower()
                points.append(normalized)
        return points
