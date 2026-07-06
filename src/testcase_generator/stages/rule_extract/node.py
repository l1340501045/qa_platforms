"""Stage 2.5: rule_extract 节点 —— 沿 PRD 章节树抽「明示业务规则」，落成规则台账。

数据源（评审 C1）：直读 seed 文档原始 markdown（`load_seed_markdown`），**不经 parsed_context**，
确保运行期节点与离线覆盖率探针卡同一套规则集。

灰度（评审 M4/M5）：`settings.rule_extract_enabled` 关时首行直通（不读文档、不调 LLM、产空台账），
不改图拓扑——保证老路径字节级回退。
"""

from __future__ import annotations

import logging

from src.testcase_generator.pipeline.config import effective_settings
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.services.llm_client import get_llm_client
from src.testcase_generator.stages.rule_extract.extractor import extract_rules
from src.testcase_generator.stages.rule_extract.source_loader import load_seed_markdown
from src.testcase_generator.stages.rule_extract.splitter import build_units

logger = logging.getLogger(__name__)


async def rule_extract_node(state: PipelineState) -> dict:
    """抽取规则台账写入 state["rules"]（list[dict]）。"""
    runtime = effective_settings(state)
    if not runtime.rule_extract_enabled:
        # 灰度关：直通，不读文档/不调 LLM，产空台账（拓扑不变，老路径完全等价）
        return {"rules": [], "current_stage": "rule_extract"}

    document_id = state["document_id"]
    md = await load_seed_markdown(document_id)
    units, digest, _classify_log = build_units(md)
    logger.info("rule_extract：seed 原文 %d 字 → %d 个规则单元", len(md), len(units))

    client = get_llm_client()
    ledger = await extract_rules(units, digest, client, concurrency=runtime.rule_extract_concurrency)
    logger.info("rule_extract：抽出 %d 条规则（失败单元 %d）", ledger.total, ledger.failed_units)

    return {
        "rules": [r.model_dump() for r in ledger.rules],
        "current_stage": "rule_extract",
    }
