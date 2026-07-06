"""一次性冻结候选集快照 → eval/retrieval/candidates.json（标注与评估的共同基准）。
只读 DB + 复跑 parse_node（便宜分类，不碰生成/视觉）。用法：uv run python eval/retrieval/snapshot_candidates.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # 仓库根 → import src

from src.platform_api.core.settings import settings
from src.testcase_generator.stages.context_utils import (
    CrossFeatureIndex,
    collect_global_sections,
)
from src.testcase_generator.stages.parse.node import parse_node

DOC_ID = "f91a9bef-bc79-429c-b6fa-63b97fd892fc"
SYS_ID = "26ffd7ba-c7ee-40e2-a1ca-b9fd413d5012"
BATCH_ID = "8c1b326b-fe7b-4ba8-8350-b92adcee23dd"
OUT = Path(__file__).parent / "candidates.json"


async def main() -> None:
    settings.entity_retrieval_enabled = False
    settings.hybrid_cross_retrieval_enabled = False
    parsed = (await parse_node({"document_id": DOC_ID, "system_id": SYS_ID, "generation_config": {}}))["parsed_context"]
    idx = await CrossFeatureIndex.build(parsed)

    candidates = [
        {
            "source_ref": c.source_ref,
            "heading": c.heading,
            "content": c.content,
            "section_kind": c.section_kind,
            "trust_level": c.trust_level,
            "source_title": c.source_title,
        }
        for c in idx._candidates
    ]
    global_keys = [[g.source_ref or "", g.heading or ""] for g in collect_global_sections(parsed)]
    features = {f.id: {"name": f.name, "source_refs": list(f.source_refs)} for f in parsed.features}

    OUT.write_text(
        json.dumps(
            {"batch_id": BATCH_ID, "candidates": candidates, "global_keys": global_keys, "features": features},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"snapshot: {len(candidates)} candidates, {len(global_keys)} global keys, {len(features)} features → {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
