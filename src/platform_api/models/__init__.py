"""共享 models 包 — knowledge-base / testcase-generator 模块通过此包访问数据模型"""

from src.platform_api.models.public import Base, System, SystemAssociation
from src.platform_api.models.knowledge import Document, DocumentAssociation, DocumentEmbedding, PrototypeLink
from src.platform_api.models.testcase import (
    TestBatch,
    TestPoint,
    TestCase,
    StageArtifact,
    QualityFlywheel,
    GoldenSetResult,
    ExportTask,
)

__all__ = [
    "Base",
    "System",
    "SystemAssociation",
    "Document",
    "DocumentAssociation",
    "DocumentEmbedding",
    "PrototypeLink",
    "TestBatch",
    "TestPoint",
    "TestCase",
    "StageArtifact",
    "QualityFlywheel",
    "GoldenSetResult",
    "ExportTask",
]
