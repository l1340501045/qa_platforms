"""从 PRD 文本抽权限矩阵（LLM）。失败安全降级返回空矩阵。"""

from __future__ import annotations

import logging

from src.testcase_generator.services.llm_client import get_llm_client
from src.testcase_generator.stages.test_points.structural.schemas import PermissionMatrix

logger = logging.getLogger(__name__)

_SYS = """你是权限建模专家。从给定 PRD 文本抽取角色×资源权限矩阵。
- roles：所有出现的角色（如 管理员/组长/投手）。
- resources：受权限控制的资源/模块（账户/商品/标题包/任务…）。
- grants：每条「某角色对某资源的某操作 允许/拒绝」，effect=allow|deny，附 source_quote（PRD 原文）。
只抽 PRD 明确写了的权限，不臆造。严格按 JSON Schema 输出。"""


async def extract_permission_matrix(prd_text: str) -> PermissionMatrix:
    try:
        return await get_llm_client().generate_structured(
            system_prompt=_SYS,
            user_content=prd_text,
            output_schema=PermissionMatrix,
            temperature=0.1,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("权限矩阵抽取失败，降级空矩阵: %s", e)
        return PermissionMatrix()
