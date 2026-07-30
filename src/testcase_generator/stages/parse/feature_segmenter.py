"""功能点切分去死板 — LLM 对标题大纲判角色，定功能点边界（切分通用化）。
只喂大纲(标题+层级+字数+短预览)，不喂全文。失败 fail-open 返回空 → 调用方回退死规则。
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from src.testcase_generator.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_PREVIEW = 120
_VALID_ROLES = {"feature_root", "container", "meta", "background"}

SEG_SYSTEM_PROMPT = """\
角色：你是需求文档结构分析员。
给你一份 PRD 的「标题大纲」（每个标题含层级、文本、正文字数、正文前若干字预览）。
任务：为每个标题判定角色，用于把文档切成「功能点」。角色四选一：
- feature_root：一个【可独立测试的业务功能】的根。其完整规格（含更深子标题内容）应折叠成一个功能点。
- container：仅是包裹/分组标题（如"功能详细说明 / 功能方案 / 需求详述"），本身不是功能点——真正的功能点在它的子标题里。
- meta：非功能信息（版本信息 / 变更日志 / 目录 / 名词解释 / 需求背景 / 需求范围模板占位等）。
- background：流程图 / 交互原型图 / 示意图 等，不含可测规格。

判定要点（与领域无关，只看结构与语义）：
- 「一个可独立测试的业务功能」= 一个 feature_root，粒度自适应：规整文档功能常在二级标题；
  嵌套文档功能常在三/四级标题（某个 container 下）。
- container 下若有多个各讲不同功能的子标题，则每个子标题判 feature_root（不要糊成一个）。
- 拿不准时判 feature_root（宁可多切，不可把真功能误判成 meta 丢掉）。
- 纯包裹标题判 container；纯图/原型判 background；纯元信息判 meta。

输出：严格按 JSON Schema，对每个输入标题给一条 {idx, role}。"""


class _RoleOut(BaseModel):
    idx: int = Field(description="回填输入标题的 idx")
    role: str = Field(description="feature_root/container/meta/background")


class _SegOutput(BaseModel):
    classifications: list[_RoleOut] = Field(description="每个标题的角色")


class FeatureSegmentationError(RuntimeError):
    """严格离线评估中的语义切分失败；不携带供应商响应正文。"""


async def decide_feature_roles(
    doc_title: str,
    triples: list[tuple[int, str, str]],
    *,
    strict: bool = False,
) -> dict[int, str]:
    """LLM 对大纲打角色；生产可回退，受控评估可选择严格失败。"""
    if not triples:
        return {}
    outline = [
        {"idx": i, "level": lv, "heading": h, "body_chars": len(b or ""), "preview": (b or "")[:_PREVIEW]}
        for i, (lv, h, b) in enumerate(triples)
    ]
    try:
        out = await get_llm_client().generate_structured(
            system_prompt=SEG_SYSTEM_PROMPT,
            user_content=json.dumps({"doc_title": doc_title, "outline": outline}, ensure_ascii=False, indent=2),
            output_schema=_SegOutput,
            temperature=0.0,
        )
    except Exception as e:  # noqa: BLE001
        if strict:
            logger.warning("严格功能点切分 LLM 失败: type=%s", type(e).__name__)
            raise FeatureSegmentationError(f"feature_segmentation_model_failed:{type(e).__name__}") from e
        logger.warning("功能点切分 LLM 失败，回退死规则: %s", e)
        return {}

    indices = [item.idx for item in out.classifications]
    normalized_roles = [(item.role or "").strip().lower() for item in out.classifications]
    if strict and (
        len(indices) != len(set(indices))
        or set(indices) != set(range(len(triples)))
        or any(role not in _VALID_ROLES for role in normalized_roles)
    ):
        raise FeatureSegmentationError("feature_segmentation_invalid_coverage")

    roles: dict[int, str] = {}
    for c in out.classifications:
        role = (c.role or "").strip().lower()
        if 0 <= c.idx < len(triples) and role in _VALID_ROLES:
            roles[c.idx] = role
    if not any(r == "feature_root" for r in roles.values()):
        logger.warning("功能点切分 LLM 未识别出任何 feature_root，回退死规则")
        if strict:
            raise FeatureSegmentationError("feature_segmentation_no_feature_root")
        return {}
    missing = [i for i in range(len(triples)) if i not in roles]
    if missing:
        logger.debug("功能点切分 LLM 漏标 idx: %s (labeled %d/%d)", missing, len(roles), len(triples))
    return roles
