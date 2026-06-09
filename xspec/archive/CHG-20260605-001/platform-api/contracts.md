# platform-api Web 后端接口契约

## 1. 概览

**本契约描述**：QA 智能平台后端 REST API 完整接口定义，覆盖系统管理、文档管理、用例生成、导出等功能域。

| 属性 | 内容 |
| :--- | :--- |
| **生产方（Provider）** | platform-api（FastAPI） |
| **消费方（Consumer）** | platform-web（React SPA） |
| **当前版本** | `v1.0.0` |
| **最后更新** | 2026-06-05 |

---

## 2. 公共约定

| 约定 | 内容 |
| :--- | :--- |
| **Base URL** | `/api/v1` |
| **数据格式** | JSON，UTF-8，Content-Type: `application/json` |
| **认证方式** | MVP 阶段无认证（单团队无登录） |
| **时间戳格式** | ISO 8601 UTC（`2026-06-05T10:30:00Z`） |

**幂等性定义**：

| 方法 | 默认幂等 |
| :---: | :---: |
| GET | 是 |
| PUT | 是 |
| DELETE | 是 |
| POST | 否（除非端点说明中标注） |
| PATCH | 否 |

**分页约定**：offset-based 分页

| 参数 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `page` | integer | 1 | 页码（从 1 开始） |
| `per_page` | integer | 20 | 每页数量（最大 100） |

**分页响应格式**：

```typescript
interface PaginatedResponse<T> {
  code: number;
  message: string;
  data: {
    items: T[];
    total: number;
    page: number;
    per_page: number;
    total_pages: number;
  };
}
```

**排序约定**：

| 参数 | 格式 | 示例 |
| :--- | :--- | :--- |
| `sort_by` | 字段名 | `created_at` |
| `sort_order` | asc / desc | `desc` |

---

## 3. 端点索引

| 端点 | 方法 | 路径 | 用途 | 认证 | 幂等 |
| :--- | :---: | :--- | :--- | :---: | :---: |
| 创建系统 | POST | `/api/v1/systems` | 创建新系统 | 否 | 否 |
| 系统列表 | GET | `/api/v1/systems` | 获取系统列表 | 否 | 是 |
| 获取系统详情 | GET | `/api/v1/systems/:id` | 获取单个系统信息 | 否 | 是 |
| 更新系统 | PUT | `/api/v1/systems/:id` | 更新系统信息 | 否 | 是 |
| 删除系统 | DELETE | `/api/v1/systems/:id` | 删除系统 | 否 | 是 |
| 创建系统关联 | POST | `/api/v1/systems/:id/associations` | 建立系统间关联 | 否 | 否 |
| 获取系统关联 | GET | `/api/v1/systems/:id/associations` | 获取系统的关联列表 | 否 | 是 |
| 删除系统关联 | DELETE | `/api/v1/systems/:id/associations/:assocId` | 删除系统关联 | 否 | 是 |
| 批量上传文档 | POST | `/api/v1/systems/:id/documents/batch` | 上传文件夹 zip | 否 | 否 |
| 文档列表 | GET | `/api/v1/systems/:id/documents` | 获取系统下文档列表 | 否 | 是 |
| 获取文档详情 | GET | `/api/v1/documents/:id` | 获取文档详情 | 否 | 是 |
| 删除文档 | DELETE | `/api/v1/documents/:id` | 删除文档 | 否 | 是 |
| 创建文档关联 | POST | `/api/v1/documents/:id/associations` | 建立文档间关联 | 否 | 否 |
| 获取文档关联 | GET | `/api/v1/documents/:id/associations` | 获取文档关联列表 | 否 | 是 |
| 触发用例生成 | POST | `/api/v1/documents/:id/generate` | 触发 AI 用例生成 | 否 | 否 |
| 获取批次详情 | GET | `/api/v1/batches/:id` | 获取批次详情和用例 | 否 | 是 |
| 提交澄清 | POST | `/api/v1/batches/:id/clarify` | 提交 Gate 澄清答案 | 否 | 是 |
| 触发迭代 | POST | `/api/v1/batches/:id/iterate` | 触发迭代优化 | 否 | 否 |
| 落库 | POST | `/api/v1/batches/:id/archive` | 确认用例落库 | 否 | 是 |
| review 用例 | PATCH | `/api/v1/testcases/:id/review` | 对单条用例 review | 否 | 否 |
| 创建导出 | POST | `/api/v1/exports` | 创建导出任务 | 否 | 否 |
| 获取导出详情 | GET | `/api/v1/exports/:id` | 获取导出状态和下载地址 | 否 | 是 |
| 导出列表 | GET | `/api/v1/exports` | 获取导出任务列表 | 否 | 是 |

---

## 4. 端点详细设计

### 4.1 创建系统

* **接口描述**：创建新的业务系统（顶层实体）
* **请求方法**：`POST`
* **请求路径**：`/api/v1/systems`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| name | string | body | 是 | 系统名称（1-100 字符） | "漫剧系统" |
| description | string | body | 否 | 系统描述 | "漫剧业务的核心系统" |

```typescript
interface CreateSystemRequest {
  name: string;
  description?: string;
}
```

#### 响应

**成功响应**（201）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "name": "漫剧系统",
    "description": "漫剧业务的核心系统",
    "created_at": "2026-06-05T10:30:00Z",
    "updated_at": "2026-06-05T10:30:00Z"
  }
}
```

**可能的错误码**：`E4091`（同名系统已存在）

---

### 4.2 系统列表

* **接口描述**：获取所有系统
* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| page | integer | query | 否 | 页码 | 1 |
| per_page | integer | query | 否 | 每页数量 | 20 |
| sort_by | string | query | 否 | 排序字段 | "created_at" |
| sort_order | string | query | 否 | 排序方向 | "desc" |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "name": "漫剧系统",
        "description": "漫剧业务的核心系统",
        "document_count": 12,
        "batch_count": 3,
        "created_at": "2026-06-05T10:30:00Z",
        "updated_at": "2026-06-05T10:30:00Z"
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

### 4.3 获取系统详情

* **接口描述**：获取单个系统的详细信息
* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems/:id`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 系统 ID | "660e8400-..." |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "name": "漫剧系统",
    "description": "漫剧业务的核心系统",
    "document_count": 12,
    "batch_count": 3,
    "associations": [
      {
        "id": "770e8400-...",
        "target_system": {
          "id": "660e8400-...",
          "name": "支付系统"
        },
        "relation_type": "api_call",
        "description": "调用支付接口"
      }
    ],
    "created_at": "2026-06-05T10:30:00Z",
    "updated_at": "2026-06-05T10:30:00Z"
  }
}
```

**可能的错误码**：`E4041`（系统不存在）

---

### 4.4 更新系统

* **接口描述**：更新系统信息
* **请求方法**：`PUT`
* **请求路径**：`/api/v1/systems/:id`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 系统 ID | "660e8400-..." |
| name | string | body | 是 | 系统名称 | "漫剧系统V2" |
| description | string | body | 否 | 系统描述 | "更新后的描述" |

```typescript
interface UpdateSystemRequest {
  name: string;
  description?: string;
}
```

#### 响应

**成功响应**（200）：与创建系统响应格式相同

**可能的错误码**：`E4041`（系统不存在）、`E4091`（同名系统已存在）

---

### 4.5 删除系统

* **接口描述**：删除系统（系统下有文档时禁止删除）
* **请求方法**：`DELETE`
* **请求路径**：`/api/v1/systems/:id`

#### 响应

**成功响应**（204）：无响应体

**可能的错误码**：`E4041`（系统不存在）、`E4091`（系统下仍有文档，无法删除）

---

### 4.6 创建系统关联

* **接口描述**：建立系统间的关联关系
* **请求方法**：`POST`
* **请求路径**：`/api/v1/systems/:id/associations`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 源系统 ID | "660e8400-..." |
| target_system_id | uuid | body | 是 | 目标系统 ID | "660e8400-..." |
| relation_type | string | body | 是 | 关联类型 | "api_call" |
| description | string | body | 否 | 关联描述 | "调用支付下单接口" |

```typescript
interface CreateSystemAssociationRequest {
  target_system_id: string;
  relation_type: "api_call" | "data_share" | "event";
  description?: string;
}
```

#### 响应

**成功响应**（201）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "770e8400-e29b-41d4-a716-446655440001",
    "source_system_id": "660e8400-...",
    "target_system_id": "660e8400-...",
    "relation_type": "api_call",
    "description": "调用支付下单接口",
    "created_at": "2026-06-05T10:30:00Z"
  }
}
```

**可能的错误码**：`E4041`（目标系统不存在）、`E4091`（关联已存在）

---

### 4.7 获取系统关联

* **接口描述**：获取系统的所有关联关系
* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems/:id/associations`

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "outgoing": [
      {
        "id": "770e8400-...",
        "target_system": { "id": "...", "name": "支付系统" },
        "relation_type": "api_call",
        "description": "调用支付下单接口"
      }
    ],
    "incoming": [
      {
        "id": "770e8400-...",
        "source_system": { "id": "...", "name": "订单系统" },
        "relation_type": "data_share",
        "description": "共享订单数据"
      }
    ]
  }
}
```

---

### 4.8 删除系统关联

* **接口描述**：删除系统间关联
* **请求方法**：`DELETE`
* **请求路径**：`/api/v1/systems/:id/associations/:assocId`

#### 响应

**成功响应**（204）：无响应体

---

### 4.9 批量上传文档

* **接口描述**：上传文件夹 zip 包到系统知识库
* **请求方法**：`POST`
* **请求路径**：`/api/v1/systems/:id/documents/batch`
* **Content-Type**：`multipart/form-data`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 系统 ID | "660e8400-..." |
| file | File | form | 是 | zip 文件（≤100MB） | docs.zip |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "uploaded": [
      {
        "id": "880e8400-...",
        "title": "需求文档-漫剧首页",
        "doc_type": "prd",
        "folder_path": "requirements/",
        "status": "uploading"
      }
    ],
    "skipped": [
      {
        "filename": "design.docx",
        "reason": "不支持的文件格式，仅接受 .md 和图片文件"
      }
    ],
    "failed": [],
    "summary": {
      "total_files": 8,
      "uploaded_count": 5,
      "skipped_count": 2,
      "failed_count": 1
    }
  }
}
```

**可能的错误码**：`E4001`（非 zip 文件）、`E4131`（文件超过 100MB）、`E4041`（系统不存在）

---

### 4.10 文档列表

* **接口描述**：获取系统下的文档列表
* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems/:id/documents`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 系统 ID | "660e8400-..." |
| page | integer | query | 否 | 页码 | 1 |
| per_page | integer | query | 否 | 每页数量 | 20 |
| doc_type | string | query | 否 | 文档类型筛选 | "prd" |
| status | string | query | 否 | 状态筛选 | "imported" |
| sort_by | string | query | 否 | 排序字段 | "created_at" |
| sort_order | string | query | 否 | 排序方向 | "desc" |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "id": "880e8400-...",
        "title": "需求文档-漫剧首页",
        "doc_type": "prd",
        "folder_path": "requirements/",
        "status": "imported",
        "association_count": 3,
        "created_at": "2026-06-05T10:30:00Z",
        "updated_at": "2026-06-05T10:35:00Z"
      }
    ],
    "total": 12,
    "page": 1,
    "per_page": 20,
    "total_pages": 1
  }
}
```

---

### 4.11 获取文档详情

* **接口描述**：获取文档详细信息（含内容预览和关联）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/documents/:id`

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "880e8400-...",
    "title": "需求文档-漫剧首页",
    "doc_type": "prd",
    "folder_path": "requirements/",
    "status": "imported",
    "storage_path": "systems/660e8400/docs/880e8400/需求文档-漫剧首页.md",
    "content_url": "https://minio.example.com/...",
    "metadata": {
      "author": "PM-Zhang",
      "version": "1.2"
    },
    "associations": [
      {
        "id": "990e8400-...",
        "target_document": { "id": "...", "title": "漫剧首页技术方案" },
        "relation_type": "req_to_tech"
      }
    ],
    "prototype_links": [
      { "id": "...", "url": "https://prototype.example.com/comic-home", "note": "首页交互原型" }
    ],
    "created_at": "2026-06-05T10:30:00Z",
    "updated_at": "2026-06-05T10:35:00Z"
  }
}
```

**可能的错误码**：`E4041`（文档不存在）

---

### 4.12 删除文档

* **接口描述**：软删除文档（有活跃批次引用时禁止）
* **请求方法**：`DELETE`
* **请求路径**：`/api/v1/documents/:id`

#### 响应

**成功响应**（204）：无响应体

**可能的错误码**：`E4041`、`E4091`（文档有进行中的生成任务，无法删除）

---

### 4.13 创建文档关联

* **接口描述**：建立文档间关联关系
* **请求方法**：`POST`
* **请求路径**：`/api/v1/documents/:id/associations`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 源文档 ID | "880e8400-..." |
| target_document_id | uuid | body | 是 | 目标文档 ID | "880e8400-..." |
| relation_type | string | body | 是 | 关联类型 | "req_to_tech" |

```typescript
interface CreateDocAssociationRequest {
  target_document_id: string;
  relation_type: "req_to_tech" | "req_to_case" | "req_to_bug" | "req_to_proto" | "tech_to_case" | "case_to_bug" | "general";
}
```

#### 响应

**成功响应**（201）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "990e8400-...",
    "source_doc_id": "880e8400-...",
    "target_doc_id": "880e8400-...",
    "relation_type": "req_to_tech",
    "created_at": "2026-06-05T10:30:00Z"
  }
}
```

**可能的错误码**：`E4041`（目标文档不存在）、`E4091`（关联已存在）

---

### 4.14 获取文档关联

* **接口描述**：获取文档的所有关联关系
* **请求方法**：`GET`
* **请求路径**：`/api/v1/documents/:id/associations`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| depth | integer | query | 否 | 关联图遍历深度（默认 1） | 2 |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "direct": [
      {
        "id": "990e8400-...",
        "document": { "id": "...", "title": "技术方案", "doc_type": "tech_doc" },
        "relation_type": "req_to_tech",
        "direction": "outgoing"
      }
    ],
    "indirect": [
      {
        "document": { "id": "...", "title": "接口定义", "doc_type": "tech_doc" },
        "path": ["需求文档 → 技术方案 → 接口定义"],
        "depth": 2
      }
    ]
  }
}
```

---

### 4.15 触发用例生成

* **接口描述**：对需求文档触发 AI 用例生成
* **请求方法**：`POST`
* **请求路径**：`/api/v1/documents/:id/generate`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 文档 ID | "880e8400-..." |

```typescript
interface GenerateRequest {
  // 当前版本无额外参数，预留扩展
}
```

#### 响应

**成功响应**（202 Accepted）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "batch_id": "aa0e8400-e29b-41d4-a716-446655440001",
    "status": "pending",
    "current_stage": "parse",
    "created_at": "2026-06-05T10:30:00Z"
  }
}
```

**可能的错误码**：`E4041`（文档不存在）、`E4001`（文档状态非 imported）、`E4091`（文档已有进行中的生成任务）

---

### 4.16 获取批次详情

* **接口描述**：获取用例批次的完整信息（含进度、用例列表）。批次状态枚举：`pending`（等待 Worker 拾取）、`running`（流水线执行中）、`suspended`（Gate NO_GO 等待澄清）、`completed`（流水线完成）、`pending_review`（等待 QA review）、`reviewing`（QA review 中）、`archived`（已落库）、`failed`（执行失败）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/batches/:id`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| id | uuid | path | 是 | 批次 ID | "aa0e8400-..." |
| page | integer | query | 否 | 用例分页页码 | 1 |
| per_page | integer | query | 否 | 每页用例数 | 20 |
| review_status | string | query | 否 | 用例 review 状态筛选 | "needs_modification" |

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "batch": {
      "id": "aa0e8400-...",
      "document_id": "880e8400-...",
      "document_title": "需求文档-漫剧首页",
      "system_id": "660e8400-...",
      "status": "running",
      "current_stage": "write-cases",
      "total_cases": null,
      "started_at": "2026-06-05T10:30:00Z",
      "completed_at": null,
      "created_at": "2026-06-05T10:30:00Z"
    },
    "stage_progress": {
      "current_stage": "write-cases",
      "stage_progress": 57,
      "total_stages": 7,
      "completed_stages": 4,
      "stages": [
        { "name": "parse", "status": "completed", "duration_ms": 5200 },
        { "name": "comprehend", "status": "completed", "duration_ms": 8300 },
        { "name": "gate", "status": "completed", "gate_result": "GO" },
        { "name": "test-points", "status": "completed", "duration_ms": 6100 },
        { "name": "write-cases", "status": "running", "progress": 75 },
        { "name": "review-cases", "status": "pending" },
        { "name": "export", "status": "pending" }
      ]
    },
    "cases": {
      "items": [],
      "total": 0,
      "page": 1,
      "per_page": 20,
      "total_pages": 0
    },
    "open_questions": null
  }
}
```

> **注**：`stage_progress` 是顶层字段（与 `batch`、`cases`、`open_questions` 同级）。  
> `stages[]` 元素中的 `duration_ms`、`progress`、`gate_result` 为可选字段，后端当前可能不返回。

**Gate NO_GO 时额外返回 open_questions**：

```json
{
  "open_questions": [
    {
      "id": "q1",
      "question": "漫剧首页的「推荐列表」排序规则是按时间还是按热度？",
      "context": "PRD §2.3 提到「推荐列表」但未明确排序规则",
      "priority": "high"
    }
  ]
}
```

**可能的错误码**：`E4041`（批次不存在）

---

### 4.17 提交澄清

* **接口描述**：提交 Gate NO_GO 的澄清答案，恢复生成任务
* **请求方法**：`POST`
* **请求路径**：`/api/v1/batches/:id/clarify`

#### 请求参数

```typescript
interface ClarifyRequest {
  answers: Array<{
    question_id: string;
    answer: string;
  }>;
}
```

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "batch_id": "aa0e8400-...",
    "status": "running",
    "message": "澄清已提交，生成任务已恢复"
  }
}
```

**可能的错误码**：`E4041`、`E4001`（批次状态非 suspended）

---

### 4.18 触发迭代

* **接口描述**：基于 review 反馈触发迭代优化（仅重新生成 needs_modification 状态的用例）
* **请求方法**：`POST`
* **请求路径**：`/api/v1/batches/:id/iterate`

#### 响应

**成功响应**（202 Accepted）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "batch_id": "aa0e8400-...",
    "status": "running",
    "iteration": 2,
    "cases_to_regenerate": 5
  }
}
```

**可能的错误码**：`E4041`、`E4001`（无 needs_modification 状态的用例）

---

### 4.19 落库

* **接口描述**：将批次中所有确认的用例落入正式库
* **请求方法**：`POST`
* **请求路径**：`/api/v1/batches/:id/archive`

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "batch_id": "aa0e8400-...",
    "status": "archived",
    "archived_count": 42,
    "archived_at": "2026-06-05T12:00:00Z"
  }
}
```

**可能的错误码**：`E4041`、`E4001`（存在未确认的用例，需全部 confirmed 后才能落库）

---

### 4.20 review 用例

* **接口描述**：对单条用例执行 review 操作
* **请求方法**：`PATCH`
* **请求路径**：`/api/v1/testcases/:id/review`

#### 请求参数

```typescript
interface ReviewTestcaseRequest {
  action: "confirmed" | "needs_modification" | "deleted";
  comment?: string;  // action 为 needs_modification 时必填
}
```

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "bb0e8400-...",
    "title": "漫剧首页-推荐列表加载正常",
    "review_status": "needs_modification",
    "review_comment": "缺少空列表状态的验证",
    "updated_at": "2026-06-05T11:00:00Z"
  }
}
```

**可能的错误码**：`E4041`、`E4001`（action 为 needs_modification 但未提供 comment）

---

### 4.21 创建导出

* **接口描述**：创建用例导出任务
* **请求方法**：`POST`
* **请求路径**：`/api/v1/exports`

#### 请求参数

```typescript
interface CreateExportRequest {
  scope: "batch" | "system";
  batch_id?: string;     // scope=batch 时必填
  system_id?: string;    // scope=system 时必填
  format: "markdown" | "excel";
}
```

#### 响应

**成功响应**（202 Accepted）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "cc0e8400-...",
    "export_scope": "batch",
    "format": "excel",
    "status": "processing",
    "created_at": "2026-06-05T12:00:00Z"
  }
}
```

**可能的错误码**：`E4001`（无可导出的已落库用例）

---

### 4.22 获取导出详情

* **接口描述**：获取导出任务状态和下载地址
* **请求方法**：`GET`
* **请求路径**：`/api/v1/exports/:id`

#### 响应

**成功响应**（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "cc0e8400-...",
    "export_scope": "batch",
    "format": "excel",
    "status": "completed",
    "file_url": "https://minio.example.com/qa-platform/exports/cc0e8400/testcases.xlsx",
    "total_cases": 42,
    "created_at": "2026-06-05T12:00:00Z",
    "completed_at": "2026-06-05T12:00:15Z"
  }
}
```

**可能的错误码**：`E4041`

---

### 4.23 导出列表

* **接口描述**：获取导出任务列表
* **请求方法**：`GET`
* **请求路径**：`/api/v1/exports`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| page | integer | query | 否 | 页码 | 1 |
| per_page | integer | query | 否 | 每页数量 | 20 |
| status | string | query | 否 | 状态筛选 | "completed" |

#### 响应

**成功响应**（200）：分页响应，items 为导出任务数组

---

## 5. 错误码

### 5.1 统一错误响应结构

```json
{
  "error_code": "E4001",
  "message": "人类可读的错误说明",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 5.2 错误码列表

| 错误码 | HTTP 状态 | 语义 | 触发条件 | 可重试 |
| :--- | :---: | :--- | :--- | :---: |
| E4001 | 400 | 请求参数无效 | 业务校验失败（如文档状态不对、缺必填字段） | 否 |
| E4041 | 404 | 资源不存在 | 指定 ID 的资源不存在 | 否 |
| E4091 | 409 | 资源冲突 | 名称重复、状态冲突（如重复生成） | 否 |
| E4131 | 413 | 请求体过大 | 文件上传超过 100MB | 否 |
| E4221 | 422 | 请求格式错误 | Pydantic 校验失败（字段类型/格式错误） | 否 |
| E4291 | 429 | 请求频率超限 | 超过速率限制 | 是（按 Retry-After 头） |
| E5001 | 500 | 服务器内部错误 | 未预期异常 | 是（自动重试 1 次） |
| E5031 | 503 | 服务不可用 | 数据库/Redis/MinIO 连接失败 | 是（退避重试） |

---

## 6. 版本策略与 Breaking Change 规则

**当前版本**：`v1`（体现在 URL 路径前缀 `/api/v1`）

**Breaking Change（必须升大版本）：**
- 删除已有端点
- 删除响应中的字段
- 修改字段类型
- 修改现有错误码的语义
- 新增请求必填字段

**非 Breaking Change（可在当前版本直接发布）：**
- 新增端点
- 新增响应中的可选字段
- 新增错误码（不修改已有）

---

## 7. 非功能约束

| 约束类型 | 值 | 超出时的行为 |
| :--- | :--- | :--- |
| 请求频率上限 | 60 次/分钟/用户 | 返回 E4291 + Retry-After 头 |
| 单次请求超时 | 30s（同步 API） | 返回 E5031 |
| 请求体最大大小 | 100 MB（文件上传）/ 1 MB（JSON） | 返回 E4131 |
| 响应体最大大小 | 10 MB | 提示使用分页 |

---

## 8. 接口安全

### 8.1 认证方式

MVP 阶段无认证（单团队无登录），所有端点无需 Token。后续版本可追加 JWT 认证。

### 8.2 安全措施

* **HTTPS 强制**：所有调用必须通过 HTTPS（生产环境）
* **输入验证**：Pydantic 模型严格校验所有参数
* **速率限制**：防止恶意请求（令牌桶算法，按 IP 限制）
* **请求 ID 追踪**：每个请求分配唯一 ID，串联日志和错误响应

---

## 9. 变更历史

| 版本 | 日期 | 变更内容 |
|:--- | :--- | :--- |
| v1.0 | 2026-06-05 | 初始版本，包含系统管理、文档管理、用例生成、导出全部接口 |
| v1.1 | 2026-06-08 | MVP 简化：移除认证端点（users/auth），系统改为顶层实体 |
| v1.2 | 2026-06-08 | batches 详情响应：stage_progress 调整为顶层字段（与 batch/cases/open_questions 同级）并补齐进度汇总字段（current_stage/stage_progress/total_stages/completed_stages）；batch 对象补齐 document_title/started_at/completed_at |
