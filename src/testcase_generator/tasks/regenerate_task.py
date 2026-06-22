"""单条用例 AI 按意见重写 — Celery 异步任务"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from src.platform_api.core.celery_app import celery_app
from src.platform_api.models.enums import ReviewStatus

logger = logging.getLogger(__name__)


@celery_app.task(name="testcase_generator.regenerate_case", bind=True)
def regenerate_case_task(self, case_id: str, comment: str) -> dict:
    """单条用例按 QA 意见重写

    1. 读取原用例 + 关联测试点
    2. 调用 LLM 带 feedback 重写
    3. 用重写结果更新原用例，iteration+1，review_status 重置
    """
    return asyncio.run(_regenerate_case(case_id, comment))


async def _regenerate_case(case_id: str, comment: str) -> dict:
    from sqlalchemy import select

    from src.platform_api.models.testcase import TestCase, TestPoint
    from src.testcase_generator.db import async_session_factory
    from src.testcase_generator.services.llm_client import get_llm_client
    from src.testcase_generator.stages.write_cases.node import WRITE_CASES_SYSTEM_PROMPT, LLMGeneratedCase

    # 1. 读取原用例和关联测试点
    async with async_session_factory() as session:
        case = await session.get(TestCase, UUID(case_id))
        if case is None:
            logger.error("regenerate_case: 用例不存在 case_id=%s", case_id)
            return {"error": "case_not_found"}

        test_point = None
        if case.test_point_id:
            tp_stmt = select(TestPoint).where(TestPoint.id == case.test_point_id)
            tp_result = await session.execute(tp_stmt)
            test_point = tp_result.scalar_one_or_none()

    # 2. 构建带 feedback 的重写 prompt
    original_case = {
        "title": case.title,
        "preconditions": case.preconditions,
        "steps": case.steps,
        "expected_results": case.expected_results,
        "priority": case.priority,
    }

    test_point_info = {}
    if test_point:
        test_point_info = {
            "dimension": test_point.dimension,
            "description": test_point.description,
            "priority": test_point.priority,
        }

    feedback_system_prompt = (
        WRITE_CASES_SYSTEM_PROMPT
        + "\n\n【重写指令】QA 修改意见是对该用例的权威纠正，优先级高于下方的原用例与原测试点描述。"
        "请先准确理解 QA 意见要表达的业务含义，再据此重写：当 QA 意见与原用例/原测试点冲突时，"
        "一律以 QA 意见为准，允许推翻原有断言、过滤规则或预期方向（例如 QA 指出某规则不成立、"
        "或实际行为与原用例相反，就按 QA 说的改，不要保留原结论）。"
        "若 QA 意见表述不够清晰，按其指向的方向理解，切勿退回原文措辞。只输出重写后的单条用例。"
    )

    user_payload = {
        "original_case": original_case,
        "test_point": test_point_info,
        "qa_feedback": comment,
    }

    try:
        llm_output = await get_llm_client().generate_structured(
            system_prompt=feedback_system_prompt,
            user_content=json.dumps(user_payload, ensure_ascii=False, indent=2),
            output_schema=LLMGeneratedCase,
            temperature=0.3,
        )
    except Exception as exc:
        logger.error("regenerate_case LLM 调用失败: case_id=%s err=%s", case_id, exc)
        return {"error": str(exc)}

    # 3. 用重写结果更新该用例
    async with async_session_factory() as session:
        case = await session.get(TestCase, UUID(case_id))
        if case is None:
            return {"error": "case_not_found_after_llm"}

        case.title = llm_output.title
        case.preconditions = llm_output.preconditions
        case.steps = [
            {
                "step_number": s.step_number,
                "action": s.action,
                "input_data": s.input_data,
                "expected_result": s.expected_result,
            }
            for s in llm_output.steps
        ]
        case.expected_results = llm_output.expected_results
        case.priority = llm_output.priority
        case.iteration = case.iteration + 1
        case.review_status = ReviewStatus.PENDING
        case.review_comment = None

        await session.commit()

    logger.info(
        "regenerate_case 完成: case_id=%s iteration=%d",
        case_id,
        case.iteration,
    )
    return {"case_id": case_id, "iteration": case.iteration, "status": "completed"}
