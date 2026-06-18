"""文档管理 Pydantic schemas"""

from datetime import datetime
from typing import Sequence
from uuid import UUID

from pydantic import BaseModel, Field, computed_field


# ─── 文档类型枚举 ───
DOC_TYPES = ("prd", "tech_doc", "test_rule", "test_case", "bug_record", "prototype", "other")

# ─── 文档关联类型枚举 ───
DOC_RELATION_TYPES = (
    "req_to_tech",
    "req_to_case",
    "req_to_bug",
    "req_to_proto",
    "tech_to_case",
    "case_to_bug",
    "general",
)


# ─── Upload Schemas ───


class UploadResponse(BaseModel):
    uploaded_count: int = Field(..., description="成功上传的文件数")
    documents: Sequence["DocumentResponse"] = Field(..., description="创建的文档列表")


# ─── Document Schemas ───


class DocumentResponse(BaseModel):
    id: UUID
    system_id: UUID
    title: str
    doc_type: str
    trust_level: int
    storage_path: str
    content: str
    content_hash: str
    embedding_status: str
    folder_path: str | None
    metadata_: dict | None = Field(None, alias="metadata_")
    image_refs: dict | list
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> str:
        """前端兼容字段：映射 embedding_status → status"""
        return self.embedding_status

    model_config = {"from_attributes": True, "populate_by_name": True}


class DocumentListResponse(BaseModel):
    items: Sequence[DocumentResponse]
    total: int
    offset: int
    limit: int


# ─── Document Association Schemas ───


class CreateDocumentAssociationRequest(BaseModel):
    source_doc_id: UUID = Field(..., description="源文档 ID")
    target_doc_id: UUID = Field(..., description="目标文档 ID")
    relation_type: str = Field(..., description="关联类型: req_to_tech / req_to_case / ...")
    created_by: str | None = Field(None, description="创建人")


class DocumentAssociationResponse(BaseModel):
    id: UUID
    source_doc_id: UUID
    target_doc_id: UUID
    relation_type: str
    created_by: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentAssociationListResponse(BaseModel):
    items: Sequence[DocumentAssociationResponse]
    total: int
    offset: int
    limit: int
