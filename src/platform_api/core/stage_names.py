"""阶段命名统一 — 内部 key → 对外 canonical 名"""

# 对外 canonical 阶段名（连字符版，与契约一致）
STAGE_CANONICAL: dict[str, str] = {
    "parse": "parse",
    "comprehend": "comprehend",
    "gate": "gate",  # Gate 不是独立节点但在进度展示里显示
    "test_points": "test-points",
    "write_cases": "write-cases",
    "review": "review-cases",
    "export": "export",
}

# 反向映射
STAGE_INTERNAL: dict[str, str] = {v: k for k, v in STAGE_CANONICAL.items()}


def to_canonical(internal_name: str) -> str:
    """内部名 → 对外名"""
    return STAGE_CANONICAL.get(internal_name, internal_name)


def to_internal(canonical_name: str) -> str:
    """对外名 → 内部名"""
    return STAGE_INTERNAL.get(canonical_name, canonical_name)


# 完整阶段列表（按执行顺序）
PIPELINE_STAGES = ["parse", "comprehend", "gate", "test-points", "write-cases", "review-cases", "export"]
