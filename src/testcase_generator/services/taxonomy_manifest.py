"""Taxonomy manifest 的规范化与内容寻址。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.testcase_generator.schemas.taxonomy import TaxonomyManifest


def load_manifest(path: str | Path) -> TaxonomyManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return TaxonomyManifest.model_validate(payload)


def canonical_manifest_dict(manifest: TaxonomyManifest) -> dict:
    payload = manifest.model_dump(mode="json", exclude_none=True)
    for node in payload["nodes"]:
        node["aliases"] = sorted(node.get("aliases", []))
    for mapping in payload["mappings"]:
        mapping["related_stable_keys"] = sorted(mapping.get("related_stable_keys", []))
    payload["nodes"] = sorted(payload["nodes"], key=lambda node: node["stable_key"])
    payload["mappings"] = sorted(
        payload["mappings"],
        key=lambda mapping: (
            mapping["document_content_hash"],
            mapping["feature_fingerprint"],
            mapping["scope"],
            json.dumps(mapping.get("selector", {}), ensure_ascii=False, sort_keys=True),
            mapping["target_stable_key"],
        ),
    )
    return payload


def manifest_hash(manifest: TaxonomyManifest) -> str:
    payload = json.dumps(
        canonical_manifest_dict(manifest),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
