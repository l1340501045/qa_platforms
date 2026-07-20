"""全平台 AI 模型配置的不可变版本模型。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.platform_api.models.public import Base


class AIModelConfigVersion(Base):
    """一次完整的四类模型配置快照。"""

    __tablename__ = "ai_model_config_versions"
    __table_args__ = (
        UniqueConstraint("revision", name="uq_ai_model_config_versions_revision"),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AIModelConfigEntry(Base):
    """一个版本中的单类模型配置；Key 只保存密文。"""

    __tablename__ = "ai_model_config_entries"
    __table_args__ = (
        UniqueConstraint("version_id", "model_role", name="uq_ai_model_config_entries_version_role"),
        CheckConstraint(
            "model_role IN ('primary', 'vision', 'verify', 'embedding')",
            name="ck_ai_model_config_entries_role",
        ),
        CheckConstraint("source IN ('environment', 'database')", name="ck_ai_model_config_entries_source"),
        CheckConstraint(
            "validation_status IN ('untested', 'passed', 'key_unreadable')",
            name="ck_ai_model_config_entries_validation",
        ),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.ai_model_config_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    model_role: Mapped[str] = mapped_column(String(20), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vector_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"AIModelConfigEntry(id={self.id!r}, model_role={self.model_role!r}, version_id={self.version_id!r})"


class AIModelConfigState(Base):
    """全平台唯一的当前有效版本指针。"""

    __tablename__ = "ai_model_config_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_ai_model_config_state_singleton"),
        {"schema": "public"},
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.ai_model_config_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
