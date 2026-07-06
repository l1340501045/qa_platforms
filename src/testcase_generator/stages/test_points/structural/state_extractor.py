"""从 PRD 文本抽状态机（LLM）。失败安全降级返回空列表。"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.testcase_generator.services.llm_client import get_llm_client
from src.testcase_generator.stages.test_points.structural.schemas import StateMachine

logger = logging.getLogger(__name__)

_SYS = """你是状态机建模专家。从给定 PRD 文本抽取所有业务实体的状态机。
对每个有明确状态流转的实体（如 任务/订单/审批/工单…）：
- name：状态机名称（即实体名）。
- states：所有出现的状态（如 待执行/执行中/已完成/已取消）。
- transitions：每条合法转移 src→dst，event（触发动作）、guard（前置条件，可空）、source_quote（PRD 原文）。
只抽 PRD 明确写了的状态和转移，不臆造。严格按 JSON Schema 输出。"""


class _SMList(BaseModel):
    machines: list[StateMachine] = Field(default_factory=list)


async def extract_state_machines(prd_text: str) -> list[StateMachine]:
    try:
        result = await get_llm_client().generate_structured(
            system_prompt=_SYS,
            user_content=prd_text,
            output_schema=_SMList,
            temperature=0.1,
        )
        return result.machines
    except Exception as e:  # noqa: BLE001
        logger.warning("状态机抽取失败，降级空列表: %s", e)
        return []
