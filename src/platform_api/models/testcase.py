"""testcase schema SQLAlchemy models"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, Float, Boolean, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.platform_api.models.public import Base


class TestBatch(Base):
    __tablename__ = "test_batches"
    __table_args__ = {"schema": "testcase"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.documents.id", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.systems.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="'pending'")
    current_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total_cases: Mapped[int | None] = mapped_column(Integer, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generation_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TestPoint(Base):
    __tablename__ = "test_points"
    __table_args__ = {"schema": "testcase"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("testcase.test_batches.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    feature_id: Mapped[str] = mapped_column(String(50), nullable=False)
    dimension: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False)
    derived_from: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TestCase(Base):
    __tablename__ = "test_cases"
    __table_args__ = {"schema": "testcase"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("testcase.test_batches.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    test_point_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("testcase.test_points.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    preconditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    steps: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expected_results: Mapped[dict] = mapped_column(JSONB, nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False)
    dimensions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)
    trust_level: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="'pending'")
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # verify 事实核验关卡产出
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bucket: Mapped[str | None] = mapped_column(String(20), nullable=True)
    verification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # dedup 全局去重产出：近重复簇规范用例逻辑 id
    duplicate_of: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    # 搜索索引列：title + steps[].action 拼接文本，应用层写入时计算
    steps_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class StageArtifact(Base):
    __tablename__ = "stage_artifacts"
    __table_args__ = {"schema": "testcase"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("testcase.test_batches.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    artifact: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    open_questions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    clarification_answers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class QualityFlywheel(Base):
    __tablename__ = "quality_flywheel"
    __table_args__ = {"schema": "testcase"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("testcase.test_cases.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False
    )
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.systems.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False
    )
    ai_version_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    qa_final_version_yaml: Mapped[str | None] = mapped_column(Text, nullable=True)
    modification_reason: Mapped[str] = mapped_column(Text, nullable=False)
    modification_type: Mapped[str] = mapped_column(String(30), nullable=False)
    feature_types: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    dimensions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    is_few_shot_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GoldenSetResult(Base):
    __tablename__ = "golden_set_results"
    __table_args__ = {"schema": "testcase"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("testcase.test_batches.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    golden_set_id: Mapped[str] = mapped_column(String(50), nullable=False)
    kernel_version: Mapped[str] = mapped_column(String(20), nullable=False)
    coverage_overlap: Mapped[float] = mapped_column(Float, nullable=False)
    ai_miss_rate: Mapped[float] = mapped_column(Float, nullable=False)
    ai_valuable_addition_rate: Mapped[float] = mapped_column(Float, nullable=False)
    direct_usability_rate: Mapped[float] = mapped_column(Float, nullable=False)
    gate_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail_report: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExportTask(Base):
    __tablename__ = "export_tasks"
    __table_args__ = {"schema": "testcase"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("testcase.test_batches.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.systems.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True
    )
    export_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="'processing'")
    file_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    total_cases: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
