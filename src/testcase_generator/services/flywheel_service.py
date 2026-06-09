"""T043: 质量飞轮 — (AI生成版, QA终版, 修改理由) 三元组存储"""

from __future__ import annotations

import logging
import uuid
from uuid import UUID

from sqlalchemy import update

from src.testcase_generator.db import async_session_factory
from src.platform_api.models.testcase import QualityFlywheel
from src.platform_api.models.enums import ModificationType

logger = logging.getLogger(__name__)


class FlywheelService:
    """质量飞轮服务

    存储 (AI 生成版, QA 终版, 修改理由) 三元组，
    用于持续优化 AI 生成质量。

    - modification_type='no_change' 的记录表示 AI 直接可用
    - is_few_shot_candidate=True 的 no_change 记录会被 few-shot 选中
    """

    async def record_flywheel_entry(
        self,
        test_case_id: UUID,
        system_id: UUID,
        ai_version_yaml: str,
        qa_final_version_yaml: str,
        modification_reason: str,
        modification_type: str,
        feature_types: list[str],
        dimensions: list[str],
    ) -> None:
        """写入 quality_flywheel 表

        Args:
            test_case_id: 关联的测试用例 ID
            system_id: 系统 ID
            ai_version_yaml: AI 生成的原始 YAML 版本
            qa_final_version_yaml: QA 最终确认版本的 YAML
            modification_reason: 修改理由
            modification_type: 修改类型枚举 (no_change/minor_edit/major_rewrite/deleted)
            feature_types: 功能类型标签列表
            dimensions: 覆盖的维度列表

        Raises:
            ValueError: modification_type 不在允许的枚举值中
        """
        # 使用枚举验证
        try:
            mod_type = ModificationType(modification_type)
        except ValueError:
            valid = [e.value for e in ModificationType]
            raise ValueError(f"Invalid modification_type '{modification_type}', must be one of {valid}")

        # no_change 自动标记为 few-shot 候选
        is_few_shot = mod_type == ModificationType.NO_CHANGE

        async with async_session_factory() as session:
            entry = QualityFlywheel(
                id=uuid.uuid4(),
                test_case_id=test_case_id,
                system_id=system_id,
                ai_version_yaml=ai_version_yaml,
                qa_final_version_yaml=qa_final_version_yaml,
                modification_reason=modification_reason,
                modification_type=mod_type.value,
                feature_types=feature_types,
                dimensions=dimensions,
                is_few_shot_candidate=is_few_shot,
            )
            session.add(entry)
            await session.commit()

        logger.info(
            "Flywheel entry recorded: case=%s type=%s few_shot=%s",
            test_case_id,
            mod_type.value,
            is_few_shot,
        )

    async def mark_few_shot_candidates(self, system_id: UUID) -> int:
        """标记 no_change 的记录为 few-shot 候选

        对指定系统下所有 modification_type='no_change' 且尚未标记的记录，
        设置 is_few_shot_candidate=True。

        Args:
            system_id: 系统 ID

        Returns:
            新标记的记录数
        """
        async with async_session_factory() as session:
            stmt = (
                update(QualityFlywheel)
                .where(
                    QualityFlywheel.system_id == system_id,
                    QualityFlywheel.modification_type == ModificationType.NO_CHANGE,
                    QualityFlywheel.is_few_shot_candidate.is_(False),
                )
                .values(is_few_shot_candidate=True)
            )
            result = await session.execute(stmt)
            await session.commit()

            count = result.rowcount
            logger.info(
                "Marked %d flywheel entries as few-shot candidates for system %s",
                count,
                system_id,
            )
            return count
