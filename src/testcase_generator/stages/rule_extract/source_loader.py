"""seed 文档原文加载器 —— node 与离线探针唯一的取文入口（根治评审 C1 取文分叉）。

为什么独立成模块：`parse_node` 产出的 `parsed_context.sources` 不是原始 markdown——它剥掉
meta/背景/目标章节、丢弃短正文、并把深层标题折叠进正文且**不带 `#` 前缀**。规则抽取若从
`parsed_context` 反拼，会与「读原文」的离线覆盖率探针卡两套规则集，导致运行期闸与回归红线
静默失效。故规则抽取与探针都必须经此唯一入口读 seed 文档的原始 `content`。
"""

from __future__ import annotations

from uuid import UUID

from src.knowledge_base.db import async_session_factory
from src.knowledge_base.repositories.document_repo import DocumentRepository


async def load_seed_markdown(document_id: str | UUID) -> str:
    """按 document_id 取 seed 文档的原始 markdown 全文（不截断、不剥离）。

    Raises:
        ValueError: 文档不存在或已软删除。
    """
    doc_uuid = document_id if isinstance(document_id, UUID) else UUID(str(document_id))
    async with async_session_factory() as session:
        repo = DocumentRepository(session)
        doc = await repo.get_by_id(doc_uuid)
        if doc is None:
            raise ValueError(f"seed 文档不存在或已删除: {doc_uuid}")
        return doc.content
