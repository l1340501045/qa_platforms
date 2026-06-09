"""集中管理 doc_type / relation_type 枚举 — 防止拼写漂移"""

from enum import StrEnum


class DocType(StrEnum):
    """文档类型（SSOT: platform-api/data-model.md §3.3）"""

    PRD = "prd"
    TECH_DOC = "tech_doc"
    TEST_RULE = "test_rule"
    TEST_CASE = "test_case"
    BUG_RECORD = "bug_record"
    PROTOTYPE = "prototype"
    OTHER = "other"


class DocRelationType(StrEnum):
    """文档间关联类型（SSOT: platform-api/data-model.md §3.4）"""

    REQ_TO_TECH = "req_to_tech"
    REQ_TO_CASE = "req_to_case"
    REQ_TO_BUG = "req_to_bug"
    REQ_TO_PROTO = "req_to_proto"
    TECH_TO_CASE = "tech_to_case"
    CASE_TO_BUG = "case_to_bug"
    GENERAL = "general"


class SystemRelationType(StrEnum):
    """系统间关联类型（SSOT: platform-api/data-model.md §3.2）"""

    API_CALL = "api_call"
    DATA_SHARE = "data_share"
    EVENT = "event"


class BatchStatus(StrEnum):
    """批次状态（SSOT: platform-api/data-model.md §3.7）"""

    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    PENDING_REVIEW = "pending_review"
    REVIEWING = "reviewing"
    ARCHIVED = "archived"
    FAILED = "failed"


class ReviewStatus(StrEnum):
    """用例 review 状态"""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    NEEDS_MODIFICATION = "needs_modification"
    DELETED = "deleted"


class ModificationType(StrEnum):
    """飞轮 modification_type 枚举"""

    NO_CHANGE = "no_change"
    MINOR_EDIT = "minor_edit"
    MAJOR_REWRITE = "major_rewrite"
    DELETED = "deleted"
