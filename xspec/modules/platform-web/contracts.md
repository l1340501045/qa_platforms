# platform-web Web 前端接口契约

## 1. 概述

本文档定义 platform-web 模块前端需要调用的 API 接口契约，与后端 platform-api/contracts.md 完全对齐。

| 属性 | 内容 |
| :--- | :--- |
| **消费方** | platform-web（React SPA） |
| **生产方** | platform-api（FastAPI），参见 `platform-api/contracts.md` |

### 公共约定

| 约定 | 内容 |
| :--- | :--- |
| **Base URL** | `/api/v1` |
| **数据格式** | JSON，UTF-8，Content-Type: `application/json` |
| **认证方式** | MVP 阶段无认证（单团队无登录） |
| **时间戳格式** | ISO 8601 UTC（`2026-06-05T10:30:00Z`） |

### 统一响应格式

```typescript
interface ApiResponse<T> {
  code: number;       // 0 表示成功
  message: string;    // "success" 或错误描述
  data: T;
}
```

### 统一错误响应格式

```typescript
interface ApiError {
  error_code: string;     // 如 "E4001"
  message: string;        // 人类可读说明
  request_id: string;     // 请求唯一 ID
}
```

---

## 2. 接口列表

### 2.1 创建系统

* **接口描述**：创建新的业务系统（顶层实体）
* **请求方法**：`POST`
* **请求路径**：`/api/v1/systems`

#### 请求参数

```typescript
interface CreateSystemRequest {
  name: string;           // 1-100 字符
  description?: string;
}
```

#### 响应

**成功响应**（201）：

```typescript
interface SystemResponse {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}
```

---

### 2.2 系统列表

* **接口描述**：获取系统列表（分页）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| page | number | query | 否 | 页码，默认 1 | 1 |
| per_page | number | query | 否 | 每页数量，默认 20 | 20 |
| sort_by | string | query | 否 | 排序字段 | "created_at" |
| sort_order | string | query | 否 | 排序方向 | "desc" |

#### 响应

```typescript
interface SystemListResponse {
  items: Array<{
    id: string;
    name: string;
    description: string | null;
    document_count: number;
    batch_count: number;
    created_at: string;
    updated_at: string;
  }>;
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}
```

---

### 2.3 获取系统详情

* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems/:id`

#### 响应

```typescript
interface SystemDetailResponse {
  id: string;
  name: string;
  description: string | null;
  document_count: number;
  batch_count: number;
  associations: Array<{
    id: string;
    target_system: { id: string; name: string };
    relation_type: "api_call" | "data_share" | "event";
    description: string | null;
  }>;
  created_at: string;
  updated_at: string;
}
```

---

### 2.4 更新系统

* **请求方法**：`PUT`
* **请求路径**：`/api/v1/systems/:id`

#### 请求参数

```typescript
interface UpdateSystemRequest {
  name: string;
  description?: string;
}
```

#### 响应

与创建系统响应格式相同

---

### 2.5 删除系统

* **请求方法**：`DELETE`
* **请求路径**：`/api/v1/systems/:id`

#### 响应

**成功响应**（204）：无响应体

---

### 2.6 创建系统关联

* **请求方法**：`POST`
* **请求路径**：`/api/v1/systems/:id/associations`

#### 请求参数

```typescript
interface CreateSystemAssociationRequest {
  target_system_id: string;
  relation_type: "api_call" | "data_share" | "event";
  description?: string;
}
```

#### 响应

**成功响应**（201）：

```typescript
interface SystemAssociationResponse {
  id: string;
  source_system_id: string;
  target_system_id: string;
  relation_type: "api_call" | "data_share" | "event";
  description: string | null;
  created_at: string;
}
```

---

### 2.7 获取系统关联

* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems/:id/associations`

#### 响应

```typescript
interface SystemAssociationsResponse {
  outgoing: Array<{
    id: string;
    target_system: { id: string; name: string };
    relation_type: "api_call" | "data_share" | "event";
    description: string | null;
  }>;
  incoming: Array<{
    id: string;
    source_system: { id: string; name: string };
    relation_type: "api_call" | "data_share" | "event";
    description: string | null;
  }>;
}
```

---

### 2.8 删除系统关联

* **请求方法**：`DELETE`
* **请求路径**：`/api/v1/systems/:id/associations/:assocId`

#### 响应

**成功响应**（204）：无响应体

---

### 2.9 批量上传文档

* **接口描述**：上传文件夹 zip 包
* **请求方法**：`POST`
* **请求路径**：`/api/v1/systems/:id/documents/batch`
* **Content-Type**：`multipart/form-data`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| file | File | form | 是 | zip 文件（≤100MB） |

#### 响应

```typescript
interface UploadResponse {
  uploaded: Array<{
    id: string;
    title: string;
    doc_type: "prd" | "tech_doc" | "test_rule" | "test_case" | "bug_record" | "prototype" | "other";
    folder_path: string | null;
    status: "uploading";
  }>;
  skipped: Array<{
    filename: string;
    reason: string;
  }>;
  failed: Array<{
    filename: string;
    error: string;
  }>;
  summary: {
    total_files: number;
    uploaded_count: number;
    skipped_count: number;
    failed_count: number;
  };
}
```

---

### 2.10 文档列表

* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems/:id/documents`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| page | number | query | 否 | 页码 |
| per_page | number | query | 否 | 每页数量 |
| doc_type | string | query | 否 | 文档类型筛选 |
| status | string | query | 否 | 状态筛选 |
| sort_by | string | query | 否 | 排序字段 |
| sort_order | string | query | 否 | 排序方向 |

#### 响应

```typescript
interface DocumentListResponse {
  items: Array<{
    id: string;
    title: string;
    doc_type: "prd" | "tech_doc" | "test_rule" | "test_case" | "bug_record" | "prototype" | "other";
    folder_path: string | null;
    status: "uploading" | "uploaded" | "importing" | "imported" | "import_failed";
    association_count: number;
    created_at: string;
    updated_at: string;
  }>;
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}
```

---

### 2.11 获取文档详情

* **请求方法**：`GET`
* **请求路径**：`/api/v1/documents/:id`

#### 响应

```typescript
interface DocumentDetailResponse {
  id: string;
  title: string;
  doc_type: "prd" | "tech_doc" | "test_rule" | "test_case" | "bug_record" | "prototype" | "other";
  folder_path: string | null;
  status: string;
  storage_path: string;
  content_url: string;
  metadata: Record<string, unknown> | null;
  associations: Array<{
    id: string;
    target_document: { id: string; title: string; doc_type: string };
    relation_type: "req_to_tech" | "req_to_case" | "req_to_bug" | "req_to_proto" | "tech_to_case" | "case_to_bug" | "general";
  }>;
  prototype_links: Array<{
    id: string;
    url: string;
    note: string | null;
  }>;
  created_at: string;
  updated_at: string;
}
```

---

### 2.12 删除文档

* **请求方法**：`DELETE`
* **请求路径**：`/api/v1/documents/:id`

#### 响应

**成功响应**（204）：无响应体

---

### 2.13 创建文档关联

* **请求方法**：`POST`
* **请求路径**：`/api/v1/documents/:id/associations`

#### 请求参数

```typescript
interface CreateDocAssociationRequest {
  target_document_id: string;
  relation_type: "req_to_tech" | "req_to_case" | "req_to_bug" | "req_to_proto" | "tech_to_case" | "case_to_bug" | "general";
}
```

#### 响应

**成功响应**（201）：

```typescript
interface DocAssociationResponse {
  id: string;
  source_doc_id: string;
  target_doc_id: string;
  relation_type: "req_to_tech" | "req_to_case" | "req_to_bug" | "req_to_proto" | "tech_to_case" | "case_to_bug" | "general";
  created_at: string;
}
```

---

### 2.14 获取文档关联

* **请求方法**：`GET`
* **请求路径**：`/api/v1/documents/:id/associations`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| depth | number | query | 否 | 遍历深度，默认 1 |

#### 响应

```typescript
interface DocAssociationsResponse {
  direct: Array<{
    id: string;
    document: { id: string; title: string; doc_type: string };
    relation_type: "req_to_tech" | "req_to_case" | "req_to_bug" | "req_to_proto" | "tech_to_case" | "case_to_bug" | "general";
    direction: "outgoing" | "incoming";
  }>;
  indirect: Array<{
    document: { id: string; title: string; doc_type: string };
    path: string[];
    depth: number;
  }>;
}
```

---

### 2.15 触发用例生成

* **接口描述**：对需求文档触发 AI 用例生成
* **请求方法**：`POST`
* **请求路径**：`/api/v1/documents/:id/generate`

#### 响应

**成功响应**（202）：

```typescript
interface GenerateResponse {
  batch_id: string;
  status: "pending";
  current_stage: "parse";
  created_at: string;
}
```

**前端处理**：获取 batch_id 后跳转到工作台页面，启动轮询

---

### 2.16 获取批次详情

* **接口描述**：获取批次完整信息（核心轮询接口）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/batches/:id`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| page | number | query | 否 | 用例分页页码 |
| per_page | number | query | 否 | 每页用例数 |
| review_status | string | query | 否 | 用例状态筛选 |

#### 响应

```typescript
interface BatchDetailResponse {
  batch: {
    id: string;
    document_id: string;
    document_title: string;
    status: "pending" | "running" | "suspended" | "completed" | "pending_review" | "reviewing" | "archived" | "failed";
    current_stage: string | null;
    stage_progress: {
      current_stage: string;
      stage_progress: number;
      total_stages: number;
      completed_stages: number;
      stages: Array<{
        name: string;
        status: "pending" | "running" | "completed" | "failed";
        progress?: number;
        duration_ms?: number;
        gate_result?: "GO" | "CONDITIONAL" | "NO_GO";
      }>;
    };
    total_cases: number | null;
    started_at: string | null;
    completed_at: string | null;
    created_at: string;
  };
  cases: {
    items: Array<{
      id: string;
      batch_id: string;
      test_point_id: string | null;
      title: string;
      preconditions: string[];
      steps: Array<{ step_number: number; action: string; input_data: string; expected_result: string }>;
      expected_results: string[];
      priority: "P0" | "P1" | "P2" | "P3";
      dimensions: string[];
      provenance: {
        derived_from: string[];
        source_section: string;
        verbatim_excerpt: string;
        trust_level: number;
      };
      trust_level: number;
      confidence_note: string | null;
      review_status: "pending" | "confirmed" | "needs_modification" | "deleted";
      review_comment: string | null;
      iteration: number;
      created_at: string;
      updated_at: string;
    }>;
    total: number;
    page: number;
    per_page: number;
    total_pages: number;
  };
  open_questions: Array<{
    id: string;
    question: string;
    context: string;
    priority: "high" | "medium" | "low";
  }> | null;
}
```

---

### 2.17 提交澄清

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

```typescript
interface ClarifyResponse {
  batch_id: string;
  status: "running";
  message: string;
}
```

**前端处理**：关闭澄清弹窗，继续轮询

---

### 2.18 触发迭代

* **请求方法**：`POST`
* **请求路径**：`/api/v1/batches/:id/iterate`

#### 响应

```typescript
interface IterateResponse {
  batch_id: string;
  status: "running";
  iteration: number;
  cases_to_regenerate: number;
}
```

**前端处理**：批次回到 running 状态，重新启动轮询

---

### 2.19 落库

* **请求方法**：`POST`
* **请求路径**：`/api/v1/batches/:id/archive`

#### 响应

```typescript
interface ArchiveResponse {
  batch_id: string;
  status: "archived";
  archived_count: number;
  archived_at: string;
}
```

**前端处理**：更新批次状态为 archived，展示成功提示

---

### 2.20 review 用例

* **请求方法**：`PATCH`
* **请求路径**：`/api/v1/testcases/:id/review`

#### 请求参数

```typescript
interface ReviewTestcaseRequest {
  action: "confirmed" | "needs_modification" | "deleted";
  comment?: string;  // action="needs_modification" 时必填
}
```

#### 响应

```typescript
interface ReviewResponse {
  id: string;
  title: string;
  review_status: "confirmed" | "needs_modification" | "deleted";
  review_comment: string | null;
  updated_at: string;
}
```

**前端处理**：即时更新用例卡片状态和样式

---

### 2.21 创建导出

* **请求方法**：`POST`
* **请求路径**：`/api/v1/exports`

#### 请求参数

```typescript
interface CreateExportRequest {
  scope: "batch" | "system";
  batch_id?: string;     // scope="batch" 时必填
  system_id?: string;    // scope="system" 时必填
  format: "markdown" | "excel";
}
```

#### 响应

**成功响应**（202）：

```typescript
interface CreateExportResponse {
  id: string;
  export_scope: "batch" | "system";
  format: "markdown" | "excel";
  status: "processing";
  created_at: string;
}
```

**前端处理**：跳转到导出中心，轮询导出状态

---

### 2.22 获取导出详情

* **请求方法**：`GET`
* **请求路径**：`/api/v1/exports/:id`

#### 响应

```typescript
interface ExportDetailResponse {
  id: string;
  export_scope: "batch" | "system";
  format: "markdown" | "excel";
  status: "processing" | "completed" | "failed";
  file_url: string | null;
  total_cases: number | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}
```

**前端处理**：status=completed 时展示下载链接（file_url）

---

### 2.23 导出列表

* **请求方法**：`GET`
* **请求路径**：`/api/v1/exports`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| page | number | query | 否 | 页码 |
| per_page | number | query | 否 | 每页数量 |
| status | string | query | 否 | 状态筛选 |

#### 响应

分页响应，items 为 ExportDetailResponse 数组

---

## 3. 错误码与前端处理

| 错误码 | HTTP 状态 | 语义 | 前端处理 | 可重试 |
| :--- | :---: | :--- | :--- | :---: |
| E4001 | 400 | 参数无效 / 业务校验失败 | message.error 展示具体原因 | 否 |
| E4041 | 404 | 资源不存在 | 跳转 404 页面或 message.error | 否 |
| E4091 | 409 | 资源冲突 | message.error 展示冲突描述 | 否 |
| E4131 | 413 | 文件过大 | message.error("文件超过 100MB 限制") | 否 |
| E4221 | 422 | 请求格式错误 | 表单字段级红框提示 | 否 |
| E4291 | 429 | 频率限制 | message.warning("请稍后重试") | 是（按 Retry-After） |
| E5001 | 500 | 服务器错误 | message.error("服务器错误，请稍后重试") | 是（自动重试 1 次） |
| E5031 | 503 | 服务不可用 | message.error("服务暂时不可用") | 是（退避重试） |

---

## 4. 轮询约定

### 4.1 用例生成进度轮询

| 配置项 | 值 |
| :--- | :--- |
| 轮询接口 | `GET /api/v1/batches/:id` |
| 轮询间隔 | 5000ms（5 秒） |
| 启动条件 | batch.status 为 `running` 或 `suspended` |
| 终止条件 | batch.status 变为 `pending_review` / `archived` / `failed` |
| 超时策略 | 无超时限制（质量优先） |
| 错误处理 | 单次请求失败不停止；连续 3 次失败暂停并提示用户 |
| 页面离开 | 自动停止轮询（useEffect cleanup） |
| 页面重进 | 检查 batch.status，若仍在 running 则自动恢复轮询 |

### 4.2 导出任务轮询

| 配置项 | 值 |
| :--- | :--- |
| 轮询接口 | `GET /api/v1/exports/:id` |
| 轮询间隔 | 3000ms（3 秒） |
| 启动条件 | export.status 为 `processing` |
| 终止条件 | export.status 变为 `completed` 或 `failed` |
| 超时策略 | 120 秒后提示"导出时间较长，请稍后查看" |

---

## 5. 认证 Token 刷新策略

MVP 阶段无认证，无需 Token 刷新。后续版本追加认证时再补充此章节。
