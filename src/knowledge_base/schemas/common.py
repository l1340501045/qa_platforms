"""Pydantic DTO 定义 — 用于服务层间数据传递"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentDTO(BaseModel):
    """文档传输对象"""

    id: UUID
    system_id: UUID
    title: str
    doc_type: str
    trust_level: int = 1
    content: str = ""
    storage_path: str = ""
    image_refs: list[str] = Field(default_factory=list)
    content_hash: str = ""
    embedding_status: str = "pending"
    folder_path: str | None = None
    metadata_: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class AssociationDTO(BaseModel):
    """文档关联传输对象"""

    id: UUID
    source_doc_id: UUID
    target_doc_id: UUID
    relation_type: str
    created_by: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class SearchRequest(BaseModel):
    """检索请求"""

    query: str = ""
    document_id: UUID | None = None
    system_id: UUID | None = None
    max_depth: int = 3
    top_k: int = 10
    type_filter: list[str] | None = None
    use_vector: bool = True
    use_graph: bool = True


class SearchResult(BaseModel):
    """单条检索结果"""

    document_id: UUID
    title: str
    content_snippet: str = ""
    score: float = 0.0
    source: str = "graph"  # graph | vector | hybrid
    depth: int | None = None
    relation_type: str | None = None


class RetrievalContext(BaseModel):
    """统一检索上下文 — 供 testcase-generator 等消费者使用"""

    seed_document_id: UUID
    system_id: UUID
    graph_results: list[SearchResult] = Field(default_factory=list)
    vector_results: list[SearchResult] = Field(default_factory=list)
    merged_results: list[SearchResult] = Field(default_factory=list)
    total_count: int = 0
