"""T044: Few-shot 提取 — 从飞轮库按条件选取样本"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select, literal_column
from sqlalchemy.dialects.postgresql import ARRAY, TEXT as PG_TEXT

from src.testcase_generator.db import async_session_factory
from src.platform_api.models.testcase import QualityFlywheel
from src.platform_api.models.enums import ModificationType

logger = logging.getLogger(__name__)


class FewShotRetriever:
    """从质量飞轮库中检索 few-shot 样本

    查询 modification_type='no_change' 且 is_few_shot_candidate=True 的记录，
    按 feature_types 交集匹配，返回 YAML 格式的用例内容供注入 prompt。

    冷启动时（无匹配记录）返回空列表，不报错。
    """

    async def retrieve_samples(
        self,
        system_id: UUID,
        feature_types: list[str],
        limit: int = 3,
    ) -> list[dict]:
        """从飞轮库检索 few-shot 样本

        查询条件（硬约束#6）：
        - system_id 匹配
        - feature_types JSONB 有交集
        - modification_type = 'no_change'
        - is_few_shot_candidate = True

        Args:
            system_id: 系统 ID
            feature_types: 功能类型列表，用于交集匹配
            limit: 最大返回数量，默认 3

        Returns:
            匹配的 few-shot 样本列表，每项包含:
            - ai_version_yaml: AI 原始生成版本
            - qa_final_version_yaml: QA 终版（no_change 时与 AI 版本相同）
            - feature_types: 功能类型标签
            - dimensions: 覆盖维度

            冷启动（空集）返回 []，不报错。
        """
        if not feature_types:
            return []

        async with async_session_factory() as session:
            # JSONB 数组交集查询
            # PostgreSQL: feature_types ?| array['type1','type2']::text[]
            # SQLAlchemy text() 中 '?' 会被当作 positional bind，需用 column 表达式规避。
            # 方案：使用 column.op('?|') 调用 PostgreSQL 操作符
            from sqlalchemy import type_coerce, cast
            from sqlalchemy.types import ARRAY as SA_ARRAY, Text

            # cast feature_types list 为 PostgreSQL text[] 字面量
            feature_arr = cast(
                literal_column(f"ARRAY{feature_types!r}"),
                SA_ARRAY(Text),
            )

            # JSONB ?| text[] — 检查 JSONB 数组是否包含 array 中任一元素
            jsonb_overlap_cond = QualityFlywheel.feature_types.op("?|")(feature_arr)

            stmt = (
                select(QualityFlywheel)
                .where(
                    QualityFlywheel.system_id == system_id,
                    QualityFlywheel.modification_type == ModificationType.NO_CHANGE,
                    QualityFlywheel.is_few_shot_candidate.is_(True),
                    jsonb_overlap_cond,
                )
                .order_by(QualityFlywheel.created_at.desc())
                .limit(limit)
            )

            result = await session.execute(stmt)
            entries = list(result.scalars().all())

        if not entries:
            logger.debug(
                "No few-shot samples found for system %s with feature_types %s (cold start)",
                system_id,
                feature_types,
            )
            return []

        samples = []
        for entry in entries:
            samples.append(
                {
                    "ai_version_yaml": entry.ai_version_yaml,
                    "qa_final_version_yaml": entry.qa_final_version_yaml,
                    "feature_types": entry.feature_types,
                    "dimensions": entry.dimensions,
                }
            )

        logger.info(
            "Retrieved %d few-shot samples for system %s",
            len(samples),
            system_id,
        )
        return samples
