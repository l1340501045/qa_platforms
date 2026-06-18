# testcase-generator 数据模型变更 — CHG-20260609-001

> 基线：xspec/modules/testcase-generator/data-model.md (v1.0)

---

## 1. 变更摘要

为支撑用例锚点匹配和版本化追溯，新增 PipelineState 字段和 3 个 Pydantic Schema（AnchorResult、VersionRecord、AnchorConfig），明确与 platform-api 物理数据模型的对应关系和质量飞轮字段对齐映射。

---

## 2. PipelineState 变更

### 2.1 新增字段

在基线 `PipelineState(TypedDict)` 基础上追加以下字段：

```python
class PipelineState(TypedDict):
    """LangGraph 全局状态"""
    # ===== 基线字段（保持不变） =====
    batch_id: str
    source_doc_id: str
    config: GenerationConfig
    parsed_context: ParsedContext | None
    comprehension_report: ComprehensionReport | None
    gate_result: GateResult | None
    test_points: list[TestPoint]
    test_cases: list[TestCase]
    audit_report: AuditReport | None
    export_result: ExportResult | None
    current_stage: str
    retry_count: int
    suspended: bool
    open_questions: list[OpenQuestion]
    user_answers: list[UserAnswer]
    few_shot_samples: list[FewShotSample]
    
    # ===== 第二段新增字段 =====
    anchor_results: list[AnchorResult]      # 锚点计算结果（write-cases 后置处理产出）
    version_records: list[VersionRecord]    # 版本写入记录（write-cases 后置处理产出）
```

### 2.2 新增字段说明

| 字段 | 类型 | 产出阶段 | 生命周期 | 说明 |
|:--- | :--- | :--- | :--- | :--- |
| `anchor_results` | `list[AnchorResult]` | write-cases 后置处理 | 持久化到 DB | 每条用例的锚点计算结果 + 匹配判定 |
| `version_records` | `list[VersionRecord]` | write-cases 后置处理 | 持久化到 DB | 每条用例的版本记录写入结果 |

### 2.3 Checkpoint 序列化格式变更

新增字段在 PostgreSQL Checkpoint（AsyncPostgresSaver）中的存储，数据以 JSONB 存储在 PostgreSQL checkpoint 表中：

```json
{
  "channel_values": {
    "...(基线字段)...": "...",
    "anchor_results": [
      {
        "case_id": "TC001",
        "anchor_key": "a1b2c3d4e5f678901234567890abcdef",
        "match_type": "deterministic",
        "logical_case_id": "lc-uuid-xxx",
        "confidence": null,
        "needs_human_confirm": false
      }
    ],
    "version_records": [
      {
        "logical_case_id": "lc-uuid-xxx",
        "version_no": 2,
        "test_case_id": "tc-uuid-xxx",
        "change_type": "ai_regen",
        "change_reason": "需求文档更新后重新生成",
        "parent_version_id": "cv-uuid-prev"
      }
    ]
  }
}
```

---

## 3. 新增 Pydantic Schema

### 3.1 AnchorResult

```python
from pydantic import BaseModel, Field
from typing import Literal

class AnchorResult(BaseModel):
    """锚点计算 + 匹配判定结果"""
    
    case_id: str = Field(
        description="用例 ID（对应 test_cases.case_seq，如 TC001）"
    )
    
    anchor_key: str = Field(
        description="MD5 hex string，32 字符。"
                    "计算规则：md5(normalize(system_id|source_section|dimension|tp_desc))"
    )
    
    match_type: Literal["deterministic", "embedding", "new"] = Field(
        description="匹配类型。"
                    "deterministic: anchor_key 精确匹配；"
                    "embedding: embedding 向量余弦相似度匹配（≥0.85）；"
                    "new: 未匹配到任何已有 logical_case"
    )
    
    logical_case_id: str | None = Field(
        default=None,
        description="匹配到的 logical_case UUID。"
                    "match_type='new' 时为新创建的 logical_case ID"
    )
    
    confidence: float | None = Field(
        default=None,
        ge=0.0, le=1.0,
        description="匹配置信度。"
                    "仅 match_type='embedding' 时有值（余弦相似度）；"
                    "match_type='deterministic' 时为 null（确定性匹配无置信度概念）；"
                    "match_type='new' 时为 null"
    )
    
    needs_human_confirm: bool = Field(
        default=False,
        description="是否需要人工确认关联关系。"
                    "规则：match_type='embedding' 时固定为 true；"
                    "其他情况为 false"
    )
```

### 3.2 VersionRecord

```python
class VersionRecord(BaseModel):
    """版本写入记录"""
    
    logical_case_id: str = Field(
        description="逻辑用例 ID（UUID）。"
                    "同一逻辑用例的所有版本共享此 ID"
    )
    
    version_no: int = Field(
        ge=1,
        description="版本号（从 1 开始递增）。"
                    "同一 logical_case 下按写入顺序递增"
    )
    
    test_case_id: str = Field(
        description="物理用例 ID（UUID）。"
                    "关联 testcase.test_cases.id"
    )
    
    change_type: Literal["ai_gen", "iteration", "ai_regen", "requirement_change", "human_edit"] = Field(
        description="变更类型。"
                    "ai_gen: 首次 AI 生成；"
                    "iteration: 用户触发迭代（修改→重生成）；"
                    "ai_regen: 同文档跨批次重新生成；"
                    "requirement_change: 需求变更后重新生成；"
                    "human_edit: QA 手工编辑"
    )
    
    change_reason: str = Field(
        default="",
        description="变更原因。"
                    "iteration: 用户填写的修改意见；"
                    "ai_regen: '同文档跨批次重新生成'；"
                    "requirement_change: 需求变更描述"
    )
    
    parent_version_id: str | None = Field(
        default=None,
        description="父版本 ID（UUID）。"
                    "指向上一个 case_version.id，形成版本链表。"
                    "version_no=1 时为 null"
    )
```

### 3.3 AnchorConfig

```python
class AnchorConfig(BaseModel):
    """锚点匹配配置"""
    
    # 精确匹配配置
    hash_algorithm: Literal["md5", "sha256"] = Field(
        default="md5",
        description="hash 算法选择。MD5 满足业务需求且计算更快"
    )
    
    # Embedding 匹配配置
    embedding_enabled: bool = Field(
        default=True,
        description="是否启用 embedding 语义兜底匹配"
    )
    
    embedding_model: str = Field(
        default="",
        description="Embedding 模型名称，由 OPENAI_EMBEDDING_MODEL 环境变量配置，走自建网关"
    )
    
    similarity_threshold: float = Field(
        default=0.85,
        ge=0.0, le=1.0,
        description="Embedding 相似度匹配阈值。"
                    "≥ 阈值: 匹配成功（标记待确认）；"
                    "< 阈值: 不匹配（创建新 logical_case）"
    )
    
    # 批量处理配置
    max_candidates_per_section: int = Field(
        default=10,
        description="同 source_section 下最多比对候选数"
    )
    
    embedding_batch_size: int = Field(
        default=100,
        description="单次 embedding API 调用的最大文本数"
    )
    
    cache_ttl_seconds: int = Field(
        default=86400,
        description="Embedding 向量缓存 TTL（秒）"
    )
    
    db_write_batch_size: int = Field(
        default=50,
        description="数据库写入批大小"
    )
```

---

## 4. 与 platform-api 数据模型的对应关系

### 4.1 物理表对照

> **物理 DDL 单一来源为 `platform-api/data-model.md`。** 本节描述 testcase-generator 模块的逻辑字段如何映射到 platform-api 定义的物理表。

| 本模块 Schema | platform-api 物理表 | Schema | 说明 |
|:--- | :--- | :--- | :--- |
| `AnchorResult.anchor_key` | `logical_case.anchor_key` | testcase | MD5 hex string 直接存储 |
| `AnchorResult.match_type` | `logical_case.anchor_method` | testcase | 记录本次关联使用的匹配方法 |
| `AnchorResult.logical_case_id` | `logical_case.id` | testcase | UUID PK |
| `AnchorResult.confidence` | `logical_case.ai_confidence` | testcase | 仅 embedding 匹配时有值 |
| `AnchorResult.needs_human_confirm` | `logical_case.needs_human_confirm` | testcase | boolean 标记 |
| `VersionRecord.logical_case_id` | `case_version.logical_case_id` | testcase | FK → logical_case.id |
| `VersionRecord.version_no` | `case_version.version_no` | testcase | 递增版本号 |
| `VersionRecord.test_case_id` | `case_version.test_case_id` | testcase | FK → test_cases.id |
| `VersionRecord.change_type` | `case_version.change_type` | testcase | 枚举值 |
| `VersionRecord.change_reason` | `case_version.change_reason` | testcase | 文本 |
| `VersionRecord.parent_version_id` | `case_version.parent_version_id` | testcase | FK → case_version.id（自引用） |

### 4.2 新增物理表（由 platform-api 建表）

以下为 platform-api 负责创建的物理表，本模块仅描述字段需求：

**logical_case 表：**

| 字段 | 类型 | 约束 | 说明 |
|:--- | :--- | :--- | :--- |
| `id` | `UUID` | PK | 逻辑用例唯一标识 |
| `system_id` | `UUID` | NOT NULL, FK → systems.id | 所属系统 |
| `anchor_key` | `VARCHAR(32)` | NOT NULL | MD5 hex string |
| `source_section` | `VARCHAR(200)` | NOT NULL | 来源段落标识 |
| `anchor_method` | `VARCHAR(20)` | NOT NULL, DEFAULT 'deterministic' | 锚定方式 |
| `ai_confidence` | `FLOAT` | 可空 | AI 匹配置信度 |
| `needs_human_confirm` | `BOOLEAN` | NOT NULL, DEFAULT false | 是否需人工确认 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT NOW() | 创建时间 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT NOW() | 更新时间 |

**case_version 表：**

| 字段 | 类型 | 约束 | 说明 |
|:--- | :--- | :--- | :--- |
| `id` | `UUID` | PK | 版本记录唯一标识 |
| `logical_case_id` | `UUID` | NOT NULL, FK → logical_case.id | 逻辑用例 ID |
| `version_no` | `INTEGER` | NOT NULL | 版本号（同 logical_case 递增） |
| `test_case_id` | `UUID` | NOT NULL, FK → test_cases.id | 物理用例 ID |
| `change_type` | `VARCHAR(30)` | NOT NULL | 变更类型枚举 |
| `change_reason` | `TEXT` | NOT NULL, DEFAULT '' | 变更原因 |
| `parent_version_id` | `UUID` | 可空, FK → case_version.id | 父版本 ID |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT NOW() | 创建时间 |

---

## 5. 质量飞轮对齐字段映射表

### 5.1 映射总览

版本写入时双写 quality_flywheel，字段对齐规则如下：

| case_version 字段 | quality_flywheel 字段 | 映射规则 |
|:--- | :--- | :--- |
| `change_type` | `modification_type` | 枚举值转换（见 5.2） |
| `change_reason` | `modification_reason` | 直接传递 |
| `test_case_id` | `test_case_id` | FK，相同 |
| `logical_case_id` | —（无对应列） | quality_flywheel 通过 test_case_id 间接关联 |

### 5.2 change_type → modification_type 枚举映射

| case_version.change_type | quality_flywheel.modification_type | 说明 |
|:--- | :--- | :--- |
| `ai_gen` | `no_change`（初始值） | 首次生成，无 QA 修改 |
| `iteration` | `major_rewrite` | 用户触发迭代视为大幅重写 |
| `ai_regen` | `no_change`（初始值） | 重新生成待 QA review |
| `requirement_change` | `no_change`（初始值） | 需求变更后重新生成，待 QA review |

**说明：** `modification_type` 的最终值在 QA review 阶段更新（由 platform-api 根据 QA 操作写入实际值）。版本写入时仅设初始值。

### 5.3 few-shot 候选标记规则

quality_flywheel.is_few_shot_candidate 在版本写入时设为 `false`，由后续流程更新：

| 场景 | is_few_shot_candidate | 更新时机 |
|:--- | :--- | :--- |
| 首次生成 | false | 版本写入时 |
| QA 无修改确认 | true | QA review 确认时（platform-api 更新） |
| QA 微调后确认 | true | QA review 确认时 |
| QA 大幅重写 | false | QA review 确认时 |
| QA 删除 | false | QA review 删除时 |

---

## 6. 索引需求（向 platform-api 提出）

本模块高频查询模式对应的索引需求：

| 索引用途 | 推荐索引 | 表 | 查询场景 |
|:--- | :--- | :--- | :--- |
| 锚点精确匹配 | `UNIQUE(system_id, anchor_key)` | logical_case | 计算 anchor_key 后查询已有 logical_case |
| 同 section 候选 | `(system_id, source_section)` | logical_case | embedding 兜底时获取候选列表 |
| 版本链查询 | `(logical_case_id, version_no)` | case_version | 查询版本历史 |
| 用例→版本 | `(test_case_id)` | case_version | 从物理用例反查版本记录 |
| 父版本链 | `(parent_version_id)` | case_version | 版本血缘追溯 |

---

## 7. 迁移影响

| 迁移操作 | 负责方 | 说明 |
|:--- | :--- | :--- |
| 创建 logical_case 表 | platform-api | Alembic 迁移 |
| 创建 case_version 表 | platform-api | Alembic 迁移 |
| 添加 PipelineState 字段 | testcase-generator | 代码变更，无 DB 迁移 |
| PostgreSQL Checkpoint 格式兼容 | testcase-generator | 新字段默认为空列表，向后兼容 |
