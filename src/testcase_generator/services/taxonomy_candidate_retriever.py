"""基于 taxonomy v2 语义的可审计 hybrid candidate retriever。"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.testcase_generator.schemas.requirement_unit import RequirementUnit
from src.testcase_generator.schemas.taxonomy import Sha256, StableKey, TaxonomyExample
from src.testcase_generator.schemas.taxonomy_resolution import (
    TaxonomyCandidate,
    TaxonomyResolutionPolicy,
)

EmbedBatchFn = Callable[[Sequence[str]], Awaitable[list[list[float]]]]
CandidateRetrieverFn = Callable[[RequirementUnit], Awaitable[list[TaxonomyCandidate]]]
TAXONOMY_RETRIEVER_REVISION = "taxonomy-candidate-retriever@1"

_SECTION_PREFIX = re.compile(
    r"^[#\s§]*(?:第\s*[一二三四五六七八九十百千零\d]+\s*[章节条款部分]?\s*[、,，.．:：\-—\s]*|"
    r"[一二三四五六七八九十百千零]+\s*[、,，.．:：\-—\s]+|"
    r"\d+(?:[.．]\d+)*[、,，.．:：\-—\s]+)"
)
_NON_SEMANTIC = re.compile(r"[\s\u3000_\-–—、,，.．:：;；!?！？()（）\[\]【】<>《》/\\]+")


class TaxonomyRetrievalError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class TaxonomySearchConcept(BaseModel):
    """带正式 concept identity 的 v2 检索视图。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    taxonomy_schema_version: Literal[2] = 2
    taxonomy_version_id: UUID
    concept_id: UUID
    stable_key: StableKey
    node_type: Literal["domain", "module", "capability"]
    node_status: Literal["active", "deprecated", "merged"]
    display_name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    definition: str = Field(min_length=1)
    scope_note: str = Field(min_length=1)
    in_scope_examples: list[TaxonomyExample] = Field(default_factory=list)
    out_of_scope_examples: list[TaxonomyExample] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sets(self) -> TaxonomySearchConcept:
        if len(self.aliases) != len(set(self.aliases)):
            raise ValueError("duplicate_alias")
        in_ids = [(item.document_content_hash, item.requirement_unit_id) for item in self.in_scope_examples]
        out_ids = [(item.document_content_hash, item.requirement_unit_id) for item in self.out_of_scope_examples]
        if len(in_ids) != len(set(in_ids)):
            raise ValueError("duplicate_in_scope_example")
        if len(out_ids) != len(set(out_ids)):
            raise ValueError("duplicate_out_of_scope_example")
        if set(in_ids) & set(out_ids):
            raise ValueError("scope_example_conflict")
        if self.node_type == "capability" and self.node_status == "active" and not self.in_scope_examples:
            raise ValueError("active_capability_in_scope_example_required")
        return self


@dataclass(frozen=True)
class IndexedOutOfScopeExample:
    example: TaxonomyExample
    vector: tuple[float, ...]


@dataclass(frozen=True)
class IndexedTaxonomyConcept:
    concept: TaxonomySearchConcept
    search_text: str
    vector: tuple[float, ...]
    out_of_scope_vectors: tuple[IndexedOutOfScopeExample, ...]


@dataclass(frozen=True)
class TaxonomyCandidateIndex:
    taxonomy_version_id: UUID
    taxonomy_manifest_hash: str
    embedding_revision: str
    retriever_revision: str
    index_policy_version: str
    vector_dimension: int
    index_hash: str
    entries: tuple[IndexedTaxonomyConcept, ...]


@dataclass(frozen=True)
class TaxonomyCandidateSourceBinding:
    retrieve_candidates: CandidateRetrieverFn
    taxonomy_version_id: UUID
    taxonomy_manifest_hash: str
    policy_version: str
    candidate_index_hash: str


class TaxonomyCandidateRetriever:
    def __init__(self, *, embed_batch: EmbedBatchFn, embedding_revision: str):
        embedding_revision = embedding_revision.strip()
        if not embedding_revision:
            raise ValueError("taxonomy_embedding_revision_required")
        self.embed_batch = embed_batch
        self.embedding_revision = embedding_revision

    def bind(
        self,
        *,
        index: TaxonomyCandidateIndex,
        policy: TaxonomyResolutionPolicy,
    ) -> TaxonomyCandidateSourceBinding:
        if index.embedding_revision != self.embedding_revision:
            raise TaxonomyRetrievalError("taxonomy_index_embedding_revision_mismatch")
        if index.retriever_revision != TAXONOMY_RETRIEVER_REVISION:
            raise TaxonomyRetrievalError("taxonomy_index_retriever_revision_mismatch")
        if index.index_policy_version != policy.candidate_index_policy_hash:
            raise TaxonomyRetrievalError("taxonomy_index_policy_mismatch")

        async def retrieve_candidates(unit: RequirementUnit) -> list[TaxonomyCandidate]:
            return await self.retrieve(unit, index=index, policy=policy)

        return TaxonomyCandidateSourceBinding(
            retrieve_candidates=retrieve_candidates,
            taxonomy_version_id=index.taxonomy_version_id,
            taxonomy_manifest_hash=index.taxonomy_manifest_hash,
            policy_version=policy.canonical_hash,
            candidate_index_hash=index.index_hash,
        )

    async def build_index(
        self,
        *,
        taxonomy_version_id: UUID,
        taxonomy_manifest_hash: Sha256,
        concepts: list[TaxonomySearchConcept],
        policy: TaxonomyResolutionPolicy,
    ) -> TaxonomyCandidateIndex:
        if any(concept.taxonomy_version_id != taxonomy_version_id for concept in concepts):
            raise TaxonomyRetrievalError("taxonomy_index_version_mismatch")
        eligible = sorted(
            (
                concept
                for concept in concepts
                if concept.node_type in policy.allowed_node_types
                and concept.node_status in policy.allowed_node_statuses
            ),
            key=lambda concept: (concept.stable_key, str(concept.concept_id)),
        )
        if not eligible:
            raise TaxonomyRetrievalError("taxonomy_index_empty")
        if len({concept.concept_id for concept in eligible}) != len(eligible):
            raise TaxonomyRetrievalError("taxonomy_index_duplicate_concept")
        if len({concept.stable_key for concept in eligible}) != len(eligible):
            raise TaxonomyRetrievalError("taxonomy_index_duplicate_stable_key")

        search_texts = [_concept_search_text(concept) for concept in eligible]
        negative_examples = [
            (concept.concept_id, example)
            for concept in eligible
            for example in sorted(
                concept.out_of_scope_examples,
                key=lambda item: (item.requirement_unit_id, item.document_content_hash, item.text),
            )
        ]
        embeddings = await self._embed(search_texts + [example.text for _, example in negative_examples])
        vector_dimension = len(embeddings[0])

        positive_vectors = embeddings[: len(eligible)]
        negative_vectors = embeddings[len(eligible) :]
        negatives_by_concept: dict[UUID, list[IndexedOutOfScopeExample]] = {}
        for (concept_id, example), vector in zip(negative_examples, negative_vectors, strict=True):
            negatives_by_concept.setdefault(concept_id, []).append(
                IndexedOutOfScopeExample(example=example, vector=tuple(vector))
            )

        entries = tuple(
            IndexedTaxonomyConcept(
                concept=concept,
                search_text=search_text,
                vector=tuple(vector),
                out_of_scope_vectors=tuple(negatives_by_concept.get(concept.concept_id, [])),
            )
            for concept, search_text, vector in zip(eligible, search_texts, positive_vectors, strict=True)
        )
        index_hash = _index_hash(
            taxonomy_version_id=taxonomy_version_id,
            taxonomy_manifest_hash=taxonomy_manifest_hash,
            embedding_revision=self.embedding_revision,
            retriever_revision=TAXONOMY_RETRIEVER_REVISION,
            index_policy_version=policy.candidate_index_policy_hash,
            eligible=eligible,
            entries=entries,
        )
        return TaxonomyCandidateIndex(
            taxonomy_version_id=taxonomy_version_id,
            taxonomy_manifest_hash=taxonomy_manifest_hash,
            embedding_revision=self.embedding_revision,
            retriever_revision=TAXONOMY_RETRIEVER_REVISION,
            index_policy_version=policy.candidate_index_policy_hash,
            vector_dimension=vector_dimension,
            index_hash=index_hash,
            entries=entries,
        )

    async def retrieve(
        self,
        unit: RequirementUnit,
        *,
        index: TaxonomyCandidateIndex,
        policy: TaxonomyResolutionPolicy,
    ) -> list[TaxonomyCandidate]:
        if index.embedding_revision != self.embedding_revision:
            raise TaxonomyRetrievalError("taxonomy_index_embedding_revision_mismatch")
        if index.retriever_revision != TAXONOMY_RETRIEVER_REVISION:
            raise TaxonomyRetrievalError("taxonomy_index_retriever_revision_mismatch")
        if index.index_policy_version != policy.candidate_index_policy_hash:
            raise TaxonomyRetrievalError("taxonomy_index_policy_mismatch")

        query_text = "\n".join((unit.title, unit.statement, unit.observable_outcome, unit.source_quote))
        query_vector = (await self._embed([query_text], expected_dimension=index.vector_dimension))[0]
        scored: list[tuple[float, str, TaxonomySearchConcept, list[str], list[str]]] = []
        for entry in index.entries:
            embedding_score = _cosine_similarity(query_vector, entry.vector)
            lexical_score, lexical_evidence = _lexical_score(unit, entry.concept, entry.search_text)
            score = max(embedding_score, lexical_score)
            conflict_evidence = _scope_conflicts(
                query_text=query_text,
                query_vector=query_vector,
                examples=entry.out_of_scope_vectors,
                threshold=policy.out_of_scope_conflict_score,
            )
            evidence = [
                *lexical_evidence,
                f"lexical_similarity:{lexical_score:.6f}",
                f"embedding_similarity:{embedding_score:.6f}",
            ]
            if conflict_evidence:
                evidence.append("out_of_scope_conflict")
            scored.append((score, entry.concept.stable_key, entry.concept, evidence, conflict_evidence))

        selected = sorted(scored, key=lambda item: (-item[0], item[1], str(item[2].concept_id)))[: policy.top_k]
        return [
            TaxonomyCandidate(
                taxonomy_version_id=index.taxonomy_version_id,
                concept_id=concept.concept_id,
                stable_key=concept.stable_key,
                score=score,
                rank=rank,
                evidence=list(dict.fromkeys(evidence)),
                scope_conflict=bool(conflict_evidence),
                scope_conflict_evidence=conflict_evidence,
            )
            for rank, (score, _, concept, evidence, conflict_evidence) in enumerate(selected, start=1)
        ]

    async def _embed(
        self,
        texts: Sequence[str],
        *,
        expected_dimension: int | None = None,
    ) -> list[list[float]]:
        try:
            embeddings = await self.embed_batch(texts)
        except Exception as exc:  # noqa: BLE001 - 屏蔽供应商错误正文
            raise TaxonomyRetrievalError(f"embedding_invocation_failed:{type(exc).__name__}") from None
        if len(embeddings) != len(texts):
            raise TaxonomyRetrievalError("embedding_count_mismatch")
        if not embeddings or not embeddings[0]:
            raise TaxonomyRetrievalError("embedding_empty_vector")
        dimension = expected_dimension or len(embeddings[0])
        if any(len(vector) != dimension for vector in embeddings):
            raise TaxonomyRetrievalError("embedding_dimension_mismatch")
        if any(not math.isfinite(value) for vector in embeddings for value in vector):
            raise TaxonomyRetrievalError("embedding_non_finite")
        return embeddings


def _concept_search_text(concept: TaxonomySearchConcept) -> str:
    parts = [
        _strip_section_prefix(concept.display_name),
        *concept.aliases,
        concept.definition,
        concept.scope_note,
        *(example.text for example in concept.in_scope_examples),
    ]
    return "\n".join(part for part in parts if part)


def _strip_section_prefix(value: str) -> str:
    return _SECTION_PREFIX.sub("", value.strip())


def _normalize_semantic_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", _strip_section_prefix(value)).casefold()
    return _NON_SEMANTIC.sub("", normalized)


def _char_ngrams(value: str, size: int = 2) -> set[str]:
    if len(value) < size:
        return {value} if value else set()
    return {value[index : index + size] for index in range(len(value) - size + 1)}


def _lexical_score(
    unit: RequirementUnit,
    concept: TaxonomySearchConcept,
    search_text: str,
) -> tuple[float, list[str]]:
    query_variants = {
        _normalize_semantic_text(unit.title),
        _normalize_semantic_text(unit.statement),
        _normalize_semantic_text(unit.structural_key),
    }
    query_variants.discard("")
    evidence: list[str] = []
    display = _normalize_semantic_text(concept.display_name)
    aliases = {_normalize_semantic_text(alias) for alias in concept.aliases}
    stable_key = _normalize_semantic_text(concept.stable_key)
    if display in query_variants:
        evidence.append("display_name_exact")
    if aliases & query_variants:
        evidence.append("alias_exact")
    if stable_key in query_variants:
        evidence.append("stable_key_exact")
    if evidence:
        return 1.0, evidence

    query = _normalize_semantic_text(" ".join((unit.title, unit.statement, unit.observable_outcome)))
    target = _normalize_semantic_text(search_text)
    query_grams = _char_ngrams(query)
    target_grams = _char_ngrams(target)
    if not query_grams or not target_grams:
        return 0.0, []
    similarity = len(query_grams & target_grams) / len(query_grams | target_grams)
    return min(1.0, similarity), []


def _scope_conflicts(
    *,
    query_text: str,
    query_vector: Sequence[float],
    examples: tuple[IndexedOutOfScopeExample, ...],
    threshold: float,
) -> list[str]:
    normalized_query = _normalize_semantic_text(query_text)
    conflicts: list[str] = []
    for indexed in examples:
        normalized_example = _normalize_semantic_text(indexed.example.text)
        exact_conflict = bool(normalized_example) and normalized_example in normalized_query
        semantic_conflict = _cosine_similarity(query_vector, indexed.vector) >= threshold
        if exact_conflict or semantic_conflict:
            conflicts.append(f"negative_example:{indexed.example.requirement_unit_id}")
    return sorted(set(conflicts))


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    cosine = sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
    return min(1.0, max(0.0, cosine))


def _index_hash(
    *,
    taxonomy_version_id: UUID,
    taxonomy_manifest_hash: str,
    embedding_revision: str,
    retriever_revision: str,
    index_policy_version: str,
    eligible: list[TaxonomySearchConcept],
    entries: tuple[IndexedTaxonomyConcept, ...],
) -> str:
    payload = {
        "taxonomy_version_id": str(taxonomy_version_id),
        "taxonomy_manifest_hash": taxonomy_manifest_hash,
        "embedding_revision": embedding_revision,
        "retriever_revision": retriever_revision,
        "index_policy_version": index_policy_version,
        "concepts": [concept.model_dump(mode="json") for concept in eligible],
        "embedding_artifact": [
            {
                "concept_id": str(entry.concept.concept_id),
                "search_text": entry.search_text,
                "vector": entry.vector,
                "out_of_scope": [
                    {
                        "requirement_unit_id": negative.example.requirement_unit_id,
                        "vector": negative.vector,
                    }
                    for negative in entry.out_of_scope_vectors
                ],
            }
            for entry in entries
        ],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
