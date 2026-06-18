# platform-api 接口契约变更 — CHG-20260609-001

> 基线：xspec/modules/platform-api/contracts.md v1.0

## 0. 文档信息

| 属性 | 内容 |
| :--- | :--- |
| **所属变更** | CHG-20260609-001 |
| **基线版本** | platform-api/contracts.md v1.0 |
| **变更类型** | modified |
| **创建时间** | 2026-06-09 |

---

## 1. 变更概述

新增 14 个 API 端点，变更 1 个已有端点，新增 5 个错误码。

| 变更类型 | 数量 | 段落 |
| :--- | :--- | :--- |
| 新增端点 | 11 | 第一段 |
| 新增端点 | 3 | 第二段 |
| 变更端点 | 1 | 第一段 |
| 新增错误码 | 5 | — |

---

## 2. 新增端点索引

| 端点 | 方法 | 路径 | 用途 | 段落 |
| :--- | :---: | :--- | :--- | :--- |
| 系统批次列表 | GET | `/api/v1/systems/:id/batches` | 系统下批次历史 | 第一段 |
| 文档批次列表 | GET | `/api/v1/documents/:id/batches` | 文档的生成批次列表 | 第一段 |
| 系统用例树 | GET | `/api/v1/systems/:id/case-tree` | 用例树形聚合 | 第一段 |
| 未读数 | GET | `/api/v1/notifications/unread-count` | 通知未读消息数 | 第一段 |
| 消息列表 | GET | `/api/v1/notifications` | 通知消息列表 | 第一段 |
| 标记已读 | PATCH | `/api/v1/notifications/:id/read` | 标记单条已读 | 第一段 |
| 全部已读 | POST | `/api/v1/notifications/mark-all-read` | 全部标记已读 | 第一段 |
| 用例搜索 | GET | `/api/v1/cases/search` | 跨系统全局搜索 | 第一段 |
| 失败重试 | POST | `/api/v1/batches/:id/retry` | 从失败阶段恢复 | 第一段 |
| 批次选项 | GET | `/api/v1/batches/options` | 导出用批次下拉 | 第一段 |
| 系统选项 | GET | `/api/v1/systems/options` | 导出用系统下拉 | 第一段 |
| 用例版本历史 | GET | `/api/v1/cases/:id/versions` | 逻辑用例版本列表 | 第二段 |
| 版本详情 | GET | `/api/v1/cases/:id/versions/:version_no` | 某版本快照 | 第二段 |
| 版本对比 | GET | `/api/v1/cases/:id/diff` | 两版本差异 | 第二段 |

---

## 3. 端点详细定义

### 3.1 系统批次列表

* **接口描述**：获取指定系统下的所有用例生成批次列表
* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems/:id/batches`
* **安全策略**：无认证（MVP）

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 系统 ID | "660e8400-..." |
| page | integer | query | 否 | 页码（默认 1） | 1 |
| per_page | integer | query | 否 | 每页数量（默认 20，最大 100） | 20 |
| status | string | query | 否 | 状态筛选 | "completed" |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "id": "aa0e8400-e29b-41d4-a716-446655440001",
        "document_id": "880e8400-e29b-41d4-a716-446655440001",
        "document_title": "需求文档-漫剧首页",
        "status": "completed",
        "total_cases": 42,
        "started_at": "2026-06-05T10:30:00Z",
        "completed_at": "2026-06-05T10:45:00Z",
        "created_at": "2026-06-05T10:29:50Z"
      }
    ],
    "total": 3,
    "page": 1,
    "per_page": 20,
    "total_pages": 1
  }
}
```

**可能的错误码**：`E4041`（系统不存在）

---

### 3.2 文档批次列表

* **接口描述**：获取指定文档的所有生成批次列表
* **请求方法**：`GET`
* **请求路径**：`/api/v1/documents/:id/batches`
* **安全策略**：无认证（MVP）

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 文档 ID | "880e8400-..." |
| page | integer | query | 否 | 页码（默认 1） | 1 |
| per_page | integer | query | 否 | 每页数量（默认 20，最大 100） | 20 |
| status | string | query | 否 | 状态筛选 | "archived" |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "id": "aa0e8400-e29b-41d4-a716-446655440001",
        "document_id": "880e8400-e29b-41d4-a716-446655440001",
        "document_title": "需求文档-漫剧首页",
        "status": "archived",
        "total_cases": 42,
        "started_at": "2026-06-05T10:30:00Z",
        "completed_at": "2026-06-05T10:45:00Z",
        "created_at": "2026-06-05T10:29:50Z"
      }
    ],
    "total": 2,
    "page": 1,
    "per_page": 20,
    "total_pages": 1
  }
}
```

**可能的错误码**：`E4041`（文档不存在）

---

### 3.3 系统用例树

* **接口描述**：获取系统级用例树形聚合数据（Document → Module → Case）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems/:id/case-tree`
* **安全策略**：无认证（MVP）

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 系统 ID | "660e8400-..." |
| batch_id | uuid | query | 否 | 指定批次 ID（默认取各文档最新完成批次） | "aa0e8400-..." |
| priority | string | query | 否 | 优先级筛选 | "P0" |
| review_status | string | query | 否 | review 状态筛选 | "confirmed" |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "tree": [
      {
        "document_id": "880e8400-e29b-41d4-a716-446655440001",
        "document_title": "需求文档-漫剧首页",
        "modules": [
          {
            "module_name": "首页推荐列表",
            "case_count": 8,
            "cases": [
              {
                "id": "bb0e8400-e29b-41d4-a716-446655440001",
                "title": "推荐列表-正常加载展示",
                "priority": "P0",
                "trust_level": 1,
                "review_status": "confirmed"
              },
              {
                "id": "bb0e8400-e29b-41d4-a716-446655440002",
                "title": "推荐列表-空状态展示",
                "priority": "P1",
                "trust_level": 2,
                "review_status": "pending"
              }
            ]
          },
          {
            "module_name": "顶部搜索栏",
            "case_count": 5,
            "cases": [...]
          }
        ]
      },
      {
        "document_id": "880e8400-e29b-41d4-a716-446655440002",
        "document_title": "需求文档-漫剧播放器",
        "modules": [...]
      }
    ]
  }
}
```

**聚合逻辑说明**：
- 未指定 `batch_id` 时，自动选取每个文档的最新已完成批次（status IN completed, archived）
- `module_name` 来自 `test_cases.provenance->>'source_section'`
- 默认排除 `review_status=deleted` 的用例
- 树根为种子文档（batch.document_id 指向的文档）

**可能的错误码**：`E4041`（系统不存在）、`E4001`（指定 batch_id 不属于该系统）

---

### 3.4 通知未读数

* **接口描述**：获取未读通知消息数量
* **请求方法**：`GET`
* **请求路径**：`/api/v1/notifications/unread-count`
* **安全策略**：无认证（MVP）

#### 请求参数

无。

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "count": 3
  }
}
```

---

### 3.5 消息列表

* **接口描述**：分页获取通知消息列表
* **请求方法**：`GET`
* **请求路径**：`/api/v1/notifications`
* **安全策略**：无认证（MVP）

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| page | integer | query | 否 | 页码（默认 1） | 1 |
| per_page | integer | query | 否 | 每页数量（默认 20，最大 100） | 20 |
| is_read | boolean | query | 否 | 已读状态筛选 | false |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "id": "dd0e8400-e29b-41d4-a716-446655440001",
        "type": "batch_completed",
        "title": "用例生成完成：需求文档-漫剧首页",
        "body": "共生成 42 条用例，请前往 Review",
        "target_type": "batch",
        "target_id": "aa0e8400-e29b-41d4-a716-446655440001",
        "read": false,
        "actor": "system",
        "created_at": "2026-06-05T10:45:00Z"
      },
      {
        "id": "dd0e8400-e29b-41d4-a716-446655440002",
        "type": "batch_failed",
        "title": "用例生成失败：需求文档-漫剧播放器",
        "body": "在 comprehend 阶段发生错误，可尝试重试",
        "target_type": "batch",
        "target_id": "aa0e8400-e29b-41d4-a716-446655440002",
        "read": false,
        "actor": "system",
        "created_at": "2026-06-05T10:40:00Z"
      }
    ],
    "total": 5,
    "page": 1,
    "per_page": 20,
    "total_pages": 1
  }
}
```

---

### 3.6 标记已读

* **接口描述**：标记单条通知为已读
* **请求方法**：`PATCH`
* **请求路径**：`/api/v1/notifications/:id/read`
* **幂等性**：是（重复调用结果一致）
* **安全策略**：无认证（MVP）

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 通知 ID | "dd0e8400-..." |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "dd0e8400-e29b-41d4-a716-446655440001",
    "read": true
  }
}
```

**可能的错误码**：`E4041`（通知不存在）

---

### 3.7 全部已读

* **接口描述**：将所有未读通知标记为已读
* **请求方法**：`POST`
* **请求路径**：`/api/v1/notifications/mark-all-read`
* **幂等性**：是（无未读时返回 updated_count=0）
* **安全策略**：无认证（MVP）

#### 请求参数

无。

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "updated_count": 3
  }
}
```

---

### 3.8 用例搜索

* **接口描述**：跨系统全局搜索用例（基于 pg_trgm 模糊匹配）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/cases/search`
* **安全策略**：无认证（MVP）

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| q | string | query | 是 | 搜索关键词（1-200 字符） | "登录验证" |
| system_id | uuid | query | 否 | 限定系统范围 | "660e8400-..." |
| priority | string | query | 否 | 优先级筛选 | "P0" |
| review_status | string | query | 否 | review 状态筛选 | "confirmed" |
| page | integer | query | 否 | 页码（默认 1） | 1 |
| per_page | integer | query | 否 | 每页数量（默认 20，最大 100） | 20 |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "id": "bb0e8400-e29b-41d4-a716-446655440001",
        "title": "登录验证-正确密码登录成功",
        "priority": "P0",
        "trust_level": 1,
        "review_status": "confirmed",
        "system_id": "660e8400-e29b-41d4-a716-446655440001",
        "system_name": "漫剧系统",
        "document_id": "880e8400-e29b-41d4-a716-446655440001",
        "document_title": "需求文档-登录模块",
        "batch_id": "aa0e8400-e29b-41d4-a716-446655440001",
        "score": 0.78,
        "created_at": "2026-06-05T10:45:00Z"
      },
      {
        "id": "bb0e8400-e29b-41d4-a716-446655440005",
        "title": "登录验证-密码错误提示",
        "priority": "P0",
        "trust_level": 1,
        "review_status": "pending",
        "system_id": "660e8400-e29b-41d4-a716-446655440001",
        "system_name": "漫剧系统",
        "document_id": "880e8400-e29b-41d4-a716-446655440001",
        "document_title": "需求文档-登录模块",
        "batch_id": "aa0e8400-e29b-41d4-a716-446655440001",
        "score": 0.65,
        "created_at": "2026-06-05T10:45:00Z"
      }
    ],
    "total": 5,
    "page": 1,
    "per_page": 20,
    "total_pages": 1
  }
}
```

**搜索机制说明**：
- 搜索范围：`steps_text` 列（title + steps[].action 拼接文本）
- 排序：pg_trgm `similarity()` 分数降序
- 匹配阈值：similarity > 0.1（降低以适应中文短关键词搜索场景）
- 排除 `review_status=deleted` 的用例

**可能的错误码**：`E4001`（q 参数为空或超过 200 字符）

---

### 3.9 失败重试

* **接口描述**：从失败阶段重试批次生成任务
* **请求方法**：`POST`
* **请求路径**：`/api/v1/batches/:id/retry`
* **安全策略**：无认证（MVP）

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 批次 ID | "aa0e8400-..." |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "batch_id": "aa0e8400-e29b-41d4-a716-446655440001",
    "status": "running",
    "fallback": false,
    "resumed_from_stage": "comprehend"
  }
}
```

**降级响应**（checkpoint 不可用时）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "batch_id": "aa0e8400-e29b-41d4-a716-446655440001",
    "status": "running",
    "fallback": true,
    "resumed_from_stage": null
  }
}
```

**字段说明**：
- `fallback`: `true` 表示 checkpoint 不可用，已降级为整批重跑
- `resumed_from_stage`: 恢复起点阶段名称（仅 fallback=false 时有值）

**可能的错误码**：`E4041`（批次不存在）、`E4092`（批次状态非 failed，不可重试）

---

### 3.10 批次选项列表

* **接口描述**：获取可导出的批次摘要列表（用于前端下拉选择器）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/batches/options`
* **安全策略**：无认证（MVP）

#### 请求参数

无。

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "id": "aa0e8400-e29b-41d4-a716-446655440001",
      "document_title": "需求文档-漫剧首页",
      "status": "archived",
      "created_at": "2026-06-05T10:29:50Z",
      "system_name": "漫剧系统"
    },
    {
      "id": "aa0e8400-e29b-41d4-a716-446655440003",
      "document_title": "需求文档-漫剧播放器",
      "status": "completed",
      "created_at": "2026-06-06T09:00:00Z",
      "system_name": "漫剧系统"
    }
  ]
}
```

**筛选规则**：仅返回 status 为 `completed` 或 `archived` 的批次。

---

### 3.11 系统选项列表

* **接口描述**：获取系统摘要列表（用于前端下拉选择器）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems/options`
* **安全策略**：无认证（MVP）

#### 请求参数

无。

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "name": "漫剧系统"
    },
    {
      "id": "660e8400-e29b-41d4-a716-446655440002",
      "name": "支付系统"
    }
  ]
}
```

---

### 3.12 用例版本历史（第二段）

* **接口描述**：获取逻辑用例的完整版本历史列表
* **请求方法**：`GET`
* **请求路径**：`/api/v1/cases/:id/versions`
* **安全策略**：无认证（MVP）

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 逻辑用例 ID（logical_case_id） | "ee0e8400-..." |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "logical_case": {
      "id": "ee0e8400-e29b-41d4-a716-446655440001",
      "system_id": "660e8400-e29b-41d4-a716-446655440001",
      "anchor_key": "660e8400|首页推荐列表|functional|a3b2c1d4e5f6",
      "anchor_method": "deterministic",
      "needs_human_confirm": false
    },
    "versions": [
      {
        "id": "ff0e8400-e29b-41d4-a716-446655440003",
        "version_no": 3,
        "test_case_id": "bb0e8400-e29b-41d4-a716-446655440010",
        "parent_version_id": "ff0e8400-e29b-41d4-a716-446655440002",
        "change_reason": "需求变更：推荐列表增加分类筛选",
        "change_type": "requirement_change",
        "actor": "ai",
        "batch_id": "aa0e8400-e29b-41d4-a716-446655440005",
        "created_at": "2026-06-08T14:00:00Z"
      },
      {
        "id": "ff0e8400-e29b-41d4-a716-446655440002",
        "version_no": 2,
        "test_case_id": "bb0e8400-e29b-41d4-a716-446655440008",
        "parent_version_id": "ff0e8400-e29b-41d4-a716-446655440001",
        "change_reason": "迭代优化：补充边界条件",
        "change_type": "iteration",
        "actor": "ai",
        "batch_id": "aa0e8400-e29b-41d4-a716-446655440003",
        "created_at": "2026-06-07T10:00:00Z"
      },
      {
        "id": "ff0e8400-e29b-41d4-a716-446655440001",
        "version_no": 1,
        "test_case_id": "bb0e8400-e29b-41d4-a716-446655440001",
        "parent_version_id": null,
        "change_reason": "首次生成",
        "change_type": "ai_gen",
        "actor": "ai",
        "batch_id": "aa0e8400-e29b-41d4-a716-446655440001",
        "created_at": "2026-06-05T10:45:00Z"
      }
    ]
  }
}
```

**可能的错误码**：`E4041`（逻辑用例不存在）

---

### 3.13 版本详情（第二段）

* **接口描述**：获取逻辑用例某个版本的完整快照
* **请求方法**：`GET`
* **请求路径**：`/api/v1/cases/:id/versions/:version_no`
* **安全策略**：无认证（MVP）

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 逻辑用例 ID | "ee0e8400-..." |
| version_no | integer | path | 是 | 版本号 | 2 |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "version": {
      "id": "ff0e8400-e29b-41d4-a716-446655440002",
      "logical_case_id": "ee0e8400-e29b-41d4-a716-446655440001",
      "version_no": 2,
      "change_reason": "迭代优化：补充边界条件",
      "change_type": "iteration",
      "actor": "ai",
      "batch_id": "aa0e8400-e29b-41d4-a716-446655440003",
      "created_at": "2026-06-07T10:00:00Z"
    },
    "test_case": {
      "id": "bb0e8400-e29b-41d4-a716-446655440008",
      "title": "推荐列表-正常加载展示",
      "preconditions": ["用户已登录", "网络正常"],
      "steps": [
        {"step_number": 1, "action": "打开首页", "input_data": "", "expected_result": "展示推荐列表"},
        {"step_number": 2, "action": "下拉刷新", "input_data": "", "expected_result": "列表更新"}
      ],
      "expected_results": ["推荐列表正确展示", "分页加载正常"],
      "priority": "P0",
      "dimensions": ["functional", "ui"],
      "provenance": {
        "derived_from": "prd-comic-home-v1.2",
        "source_section": "首页推荐列表",
        "verbatim_excerpt": "首页需展示推荐内容列表...",
        "trust_level": 1
      },
      "trust_level": 1,
      "review_status": "pending",
      "iteration": 2
    }
  }
}
```

**可能的错误码**：`E4041`（逻辑用例不存在或版本号不存在）

---

### 3.14 版本对比（第二段）

* **接口描述**：对比逻辑用例的两个版本差异
* **请求方法**：`GET`
* **请求路径**：`/api/v1/cases/:id/diff`
* **安全策略**：无认证（MVP）

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 逻辑用例 ID | "ee0e8400-..." |
| v1 | integer | query | 是 | 基准版本号 | 1 |
| v2 | integer | query | 是 | 对比版本号 | 2 |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "logical_case_id": "ee0e8400-e29b-41d4-a716-446655440001",
    "v1": 1,
    "v2": 2,
    "old": {
      "version_no": 1,
      "title": "推荐列表-加载展示",
      "preconditions": ["用户已登录"],
      "steps": [
        {"step_number": 1, "action": "打开首页", "input_data": "", "expected_result": "展示推荐列表"}
      ],
      "expected_results": ["推荐列表正确展示"],
      "priority": "P0",
      "dimensions": ["functional"],
      "provenance": {
        "derived_from": "prd-comic-home-v1.0",
        "source_section": "首页推荐列表",
        "verbatim_excerpt": "首页需展示推荐内容列表...",
        "trust_level": 1
      },
      "change_reason": "首次生成",
      "change_type": "ai_gen",
      "actor": "ai",
      "created_at": "2026-06-05T10:45:00Z"
    },
    "new": {
      "version_no": 2,
      "title": "推荐列表-正常加载展示",
      "preconditions": ["用户已登录", "网络正常"],
      "steps": [
        {"step_number": 1, "action": "打开首页", "input_data": "", "expected_result": "展示推荐列表"},
        {"step_number": 2, "action": "下拉刷新", "input_data": "", "expected_result": "列表更新"}
      ],
      "expected_results": ["推荐列表正确展示", "分页加载正常"],
      "priority": "P0",
      "dimensions": ["functional", "ui"],
      "provenance": {
        "derived_from": "prd-comic-home-v1.2",
        "source_section": "首页推荐列表",
        "verbatim_excerpt": "首页需展示推荐内容列表...",
        "trust_level": 1
      },
      "change_reason": "需求变更后重新生成",
      "change_type": "requirement_change",
      "actor": "ai",
      "created_at": "2026-06-07T10:00:00Z"
    }
  }
}
```

**可能的错误码**：`E4041`（逻辑用例不存在）、`E4001`（v1 或 v2 版本号不存在、v1 >= v2）

---

## 4. 变更端点

### 4.1 获取批次详情（增强）

* **基线路径**：`GET /api/v1/batches/:id`
* **变更内容**：`stage_progress.stages` 数组元素增加透传字段

#### 新增字段

| 字段 | 类型 | 说明 | 来源 |
| :--- | :--- | :--- | :--- |
| `stages[].duration_ms` | integer \| null | 阶段执行耗时（毫秒） | stage_artifacts.duration_ms |
| `stages[].started_at` | string \| null | 阶段开始时间 | stage_artifacts.started_at |
| `stages[].completed_at` | string \| null | 阶段完成时间 | stage_artifacts.completed_at |
| `stages[].error_message` | string \| null | 失败原因（仅 status=failed 时） | stage_artifacts.artifact.error |

#### 增强后响应示例（stage_progress 部分）

```json
{
  "stage_progress": {
    "current_stage": "write-cases",
    "stage_progress": 75,
    "total_stages": 7,
    "completed_stages": 4,
    "stages": [
      {
        "name": "parse",
        "status": "completed",
        "duration_ms": 5200,
        "started_at": "2026-06-05T10:30:00Z",
        "completed_at": "2026-06-05T10:30:05Z",
        "error_message": null
      },
      {
        "name": "comprehend",
        "status": "failed",
        "duration_ms": 8300,
        "started_at": "2026-06-05T10:30:05Z",
        "completed_at": "2026-06-05T10:30:13Z",
        "error_message": "LLM 返回格式解析失败：Expected JSON object but got string"
      }
    ]
  }
}
```

**兼容性**：新增字段为可选（nullable），不影响现有消费方。

---

## 5. 错误码新增列表

| 错误码 | HTTP 状态 | 语义 | 触发条件 | 可重试 |
| :--- | :---: | :--- | :--- | :---: |
| E4002 | 400 | 搜索参数无效 | q 参数为空或超过 200 字符 | 否 |
| E4042 | 404 | 通知不存在 | 标记已读时指定 ID 的通知不存在 | 否 |
| E4043 | 404 | 逻辑用例不存在 | 查询版本时 logical_case_id 不存在 | 否 |
| E4092 | 409 | 状态不允许操作 | 批次状态非 failed 时调用 retry | 否 |
| E4093 | 409 | 版本不存在 | diff 时指定的 v1 或 v2 版本号不存在 | 否 |

---

## 6. trust_level 语义修正说明

**问题**：`trust_level` 字段后端返回整数 1–5，含义为"信源信任度，数字越小越可信"。前端此前误按 0-1 浮点数 ×100 展示为百分比，导致恒显示 100%。

**修正规则**：

| trust_level 值 | 语义 | confidence_note 规则 | 前端展示建议 |
| :---: | :--- | :--- | :--- |
| 1 | 高可信 | 无 | 绿色标签"高可信" |
| 2 | 高可信 | 无 | 绿色标签"高可信" |
| 3 | 中可信 | 无 | 黄色标签"中可信" |
| 4 | 中可信 | 必填（如"来源为 UI 设计稿，建议人工确认交互细节"） | 黄色标签"中可信" + note 提示 |
| 5 | 低可信 | 必填（如"来源含原型探索，原型可能有交互 bug"） | 红色标签"低可信" + note 提示 |

**API 层约定**：
- 响应中 `trust_level` 继续返回整数 1–5，**禁止**转为百分比或浮点数
- `confidence_note` 字段（`test_cases.confidence_note`）在 trust_level >= 4 时由 AI 生成端填充
- 前端按上表映射为三档标签 + confidence_note 文字展示

---

## 7. 变更历史

| 版本 | 日期 | 变更内容 |
| :--- | :--- | :--- |
| v1.0 | 2026-06-05 | 初始版本 |
| v1.1 | 2026-06-08 | MVP 简化 |
| v1.2 | 2026-06-08 | stage_progress 调整 |
| **v1.3** | **2026-06-09** | **CHG-20260609-001：新增 11+3 端点、trust_level 修正、stage_progress 透传增强** |
