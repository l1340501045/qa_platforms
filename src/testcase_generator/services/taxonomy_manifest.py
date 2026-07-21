"""Taxonomy manifest 的规范化与内容寻址。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.testcase_generator.schemas.taxonomy import TaxonomyAssignmentSet, TaxonomyManifest


def load_manifest(path: str | Path) -> TaxonomyManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return TaxonomyManifest.model_validate(payload)


def load_assignment_set(path: str | Path) -> TaxonomyAssignmentSet:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return TaxonomyAssignmentSet.model_validate(payload)


def canonical_manifest_dict(manifest: TaxonomyManifest) -> dict[str, Any]:
    payload = manifest.model_dump(mode="json", exclude_none=True)
    for node in payload["nodes"]:
        node["aliases"] = sorted(node.get("aliases", []))
        _sort_scope_examples(node)
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


def taxonomy_definition_hash(manifest: TaxonomyManifest) -> str:
    return taxonomy_node_definition_hash([node.model_dump(mode="json", exclude_none=True) for node in manifest.nodes])


def taxonomy_node_definition_hash(nodes: list[dict[str, Any]]) -> str:
    canonical_nodes: list[dict[str, Any]] = []
    for node in nodes:
        normalized = dict(node)
        normalized["aliases"] = sorted(normalized.get("aliases", []))
        _sort_scope_examples(normalized)
        canonical_nodes.append(normalized)
    payload = json.dumps(
        sorted(canonical_nodes, key=lambda node: node["stable_key"]),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sort_scope_examples(node: dict[str, Any]) -> None:
    for field_name in ("in_scope_examples", "out_of_scope_examples"):
        if not node.get(field_name):
            node.pop(field_name, None)
            continue
        node[field_name] = sorted(
            node[field_name],
            key=lambda example: (
                example["document_content_hash"],
                example["requirement_unit_id"],
                example["text"],
            ),
        )


def assignment_hash(assignments: TaxonomyAssignmentSet) -> str:
    payload = assignments.model_dump(mode="json", exclude_none=True)
    for assignment in payload["assignments"]:
        assignment["related_stable_keys"] = sorted(assignment.get("related_stable_keys", []))
    payload["assignments"] = sorted(payload["assignments"], key=lambda item: item["case_id"])
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
