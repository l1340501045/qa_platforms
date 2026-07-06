# platform-web 接口契约变更 — CHG-20260609-001

> 基线：xspec/modules/platform-web/contracts.md (v1.0)

## 变更摘要

新增 12 个 API 调用（通知、用例树、搜索、批次操作、下拉选项、版本对比），新增 2 个 Service 文件（notificationAPI.ts、caseAPI.ts），增强错误处理策略。

---

## 新增 API 调用列表

### 2.24 获取系统批次列表

* **接口描述**：获取指定系统下的所有批次（批次历史 Tab）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems/:id/batches`
* **所属 Service**：`batchAPI.ts`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| page | number | query | 否 | 页码，默认 1 |
| per_page | number | query | 否 | 每页数量，默认 20 |
| status | string | query | 否 | 批次状态筛选 |
| sort_by | string | query | 否 | 排序字段，默认 created_at |
| sort_order | string | query | 否 | 排序方向，默认 desc |

#### 响应

```typescript
interface SystemBatchListResponse {
  items: Array<{
    id: string;
    document_id: string;
    document_title: string;
    status: BatchStatus;
    current_stage: PipelineStage | null;
    total_cases: number | null;
    started_at: string | null;
    completed_at: string | null;
    created_at: string;
  }>;
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}
```

#### 错误处理

| 状态码 | 处理策略 |
| :--- | :--- |
| 404 | 系统不存在，跳转 404 页面 |
| 500 | message.error + 展示重试按钮 |

---

### 2.25 获取系统用例树

* **接口描述**：获取指定系统的用例树嵌套数据（后端已组装为 Document → Module → Case 三级树）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems/:id/case-tree`
* **所属 Service**：`caseAPI.ts`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| batch_id | string | query | 否 | 指定批次 ID（默认取各文档最新完成批次） |
| priority | string | query | 否 | 优先级筛选（P0/P1/P2/P3） |
| review_status | string | query | 否 | review 状态筛选 |

#### 响应

```typescript
interface CaseTreeResponse {
  tree: Array<{
    document_id: string;
    document_title: string;
    modules: Array<{
      module_name: string;   // 来自 provenance.source_section
      case_count: number;
      cases: Array<{
        id: string;
        title: string;
        priority: "P0" | "P1" | "P2" | "P3";
        trust_level: number;
        review_status: "pending" | "confirmed" | "needs_modification" | "deleted";
      }>;
    }>;
  }>;
}
```

#### 错误处理

| 状态码 | 处理策略 |
| :--- | :--- |
| 404 | 系统不存在，跳转 404 页面 |
| 500 | message.error + EmptyState 展示"加载失败" |

---

### 2.26 获取未读通知数

* **接口描述**：获取当前用户未读通知数量（轮询调用，极轻量）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/notifications/unread-count`
* **所属 Service**：`notificationAPI.ts`
* **轮询间隔**：10000ms

#### 响应

```typescript
interface UnreadCountResponse {
  count: number;
}
```

#### 错误处理

| 状态码 | 处理策略 |
| :--- | :--- |
| 任意错误 | 静默失败，保持上次 Badge 数值，下次轮询重试 |

---

### 2.27 获取通知列表

* **接口描述**：获取通知消息列表（分页）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/notifications`
* **所属 Service**：`notificationAPI.ts`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| page | number | query | 否 | 页码，默认 1 |
| per_page | number | query | 否 | 每页数量，默认 20 |
| read | boolean | query | 否 | 筛选已读/未读 |

#### 响应

```typescript
interface NotificationListResponse {
  items: Array<{
    id: string;
    type: "batch_completed" | "batch_failed" | "batch_suspended" | "export_completed" | "export_failed" | "system_message";
    title: string;
    content: string;
    target_id: string;
    target_type: "batch" | "export" | "system";
    read: boolean;
    created_at: string;
  }>;
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}
```

#### 错误处理

| 状态码 | 处理策略 |
| :--- | :--- |
| 500 | message.error("获取通知失败") |

---

### 2.28 标记通知已读

* **接口描述**：标记单条通知为已读
* **请求方法**：`PATCH`
* **请求路径**：`/api/v1/notifications/:id/read`
* **所属 Service**：`notificationAPI.ts`

#### 响应

```typescript
interface MarkReadResponse {
  id: string;
  read: true;
  updated_at: string;
}
```

#### 错误处理

| 状态码 | 处理策略 |
| :--- | :--- |
| 404 | 静默失败（通知可能已被删除） |
| 500 | 静默失败，不影响用户跳转 |

**前端处理**：乐观更新（先本地标记已读，再发请求），请求失败时回滚。

---

### 2.29 全部标记已读

* **接口描述**：将当前用户所有未读通知标记为已读
* **请求方法**：`POST`
* **请求路径**：`/api/v1/notifications/mark-all-read`
* **所属 Service**：`notificationAPI.ts`

#### 响应

```typescript
interface MarkAllReadResponse {
  updated_count: number;
}
```

#### 错误处理

| 状态码 | 处理策略 |
| :--- | :--- |
| 500 | message.error("操作失败，请重试") |

**前端处理**：乐观更新，将 unreadCount 置为 0，请求失败时恢复原值。

---

### 2.30 全局用例搜索

* **接口描述**：跨系统/跨文档搜索用例
* **请求方法**：`GET`
* **请求路径**：`/api/v1/cases/search`
* **所属 Service**：`caseAPI.ts`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| keyword | string | query | 是 | 搜索关键词，1-200 字符 |
| system_id | string | query | 否 | 限定系统 ID |
| priority | string | query | 否 | 优先级筛选 |
| review_status | string | query | 否 | review 状态筛选 |
| trust_level | number | query | 否 | 信任等级筛选（1-5） |
| page | number | query | 否 | 页码，默认 1 |
| per_page | number | query | 否 | 每页数量，默认 20 |

#### 响应

```typescript
interface SearchResponse {
  items: Array<{
    case_id: string;
    case_title: string;
    system_id: string;
    system_name: string;
    document_id: string;
    document_title: string;
    priority: "P0" | "P1" | "P2" | "P3";
    trust_level: number;
    review_status: "pending" | "confirmed" | "needs_modification" | "deleted";
    highlight: string;         // 搜索匹配高亮片段（含 <mark> 标签）
    updated_at: string;
  }>;
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}
```

#### 错误处理

| 状态码 | 处理策略 |
| :--- | :--- |
| 400 | keyword 为空时前端拦截，不发请求 |
| 500 | message.error("搜索失败") + 保持上次结果 |

**前端处理**：
- 输入框防抖 300ms
- 点击搜索或按回车立即触发
- 搜索中展示 Loading 状态
- highlight 字段直接 dangerouslySetInnerHTML 渲染（后端已做 XSS 过滤）

---

### 2.31 批次重试

* **接口描述**：从失败的阶段重试批次执行
* **请求方法**：`POST`
* **请求路径**：`/api/v1/batches/:id/retry`
* **所属 Service**：`batchAPI.ts`

#### 请求参数

```typescript
interface RetryBatchRequest {
  from_stage?: PipelineStage;  // 从哪个阶段重试，默认从失败阶段开始
}
```

#### 响应

```typescript
interface RetryBatchResponse {
  batch_id: string;
  status: "running";
  from_stage: string;
  message: string;
}
```

#### 错误处理

| 状态码 | 处理策略 |
| :--- | :--- |
| 400 | 批次非失败状态，message.error("当前批次无法重试") |
| 404 | 批次不存在 |
| 409 | 批次正在运行中，message.warning("批次正在运行中") |
| 500 | message.error("重试失败") + 允许再次点击重试 |

**前端处理**：重试成功后自动恢复轮询。

---

### 2.32 获取批次下拉选项

* **接口描述**：获取系统下的批次简要列表（用于导出页面下拉选择）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/batches/options`
* **所属 Service**：`batchAPI.ts`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| system_id | string | query | 是 | 系统 ID |
| status | string | query | 否 | 状态筛选，默认 archived |

#### 响应

```typescript
interface BatchOptionsResponse {
  items: Array<{
    id: string;
    document_title: string;
    status: string;
    total_cases: number | null;
    created_at: string;
  }>;
}
```

#### 错误处理

| 状态码 | 处理策略 |
| :--- | :--- |
| 500 | 下拉显示"加载失败"选项 |

---

### 2.33 获取系统下拉选项

* **接口描述**：获取系统简要列表（用于搜索/导出页面下拉选择）
* **请求方法**：`GET`
* **请求路径**：`/api/v1/systems/options`
* **所属 Service**：`systemAPI.ts`

#### 响应

```typescript
interface SystemOptionsResponse {
  items: Array<{
    id: string;
    name: string;
    document_count: number;
    batch_count: number;
  }>;
}
```

#### 错误处理

| 状态码 | 处理策略 |
| :--- | :--- |
| 500 | 下拉显示"加载失败"选项 |

---

### 2.34 获取用例版本列表（第二段）

* **接口描述**：获取指定用例的所有历史版本
* **请求方法**：`GET`
* **请求路径**：`/api/v1/cases/:id/versions`
* **所属 Service**：`caseAPI.ts`

#### 响应

```typescript
interface CaseVersionsResponse {
  versions: Array<{
    version: number;
    iteration: number;
    modification_type: "generated" | "iterated" | "manual_edit";
    modification_reason: string | null;
    created_at: string;
  }>;
  total_versions: number;
}
```

#### 错误处理

| 状态码 | 处理策略 |
| :--- | :--- |
| 404 | 用例不存在或无版本历史 |
| 500 | message.error("获取版本历史失败") |

---

### 2.35 获取用例版本对比（第二段）

* **接口描述**：获取指定用例两个版本的原始数据，前端使用 jsdiff 进行差异对比
* **请求方法**：`GET`
* **请求路径**：`/api/v1/cases/:id/diff`
* **所属 Service**：`caseAPI.ts`

#### 请求参数

| 参数名 | 类型 | 位置 | 必填 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| v1 | number | query | 是 | 旧版本号 |
| v2 | number | query | 是 | 新版本号 |

#### 响应

```typescript
interface CaseDiffResponse {
  case_id: string;
  old_version: {
    version: number;
    title: string;
    preconditions: string[];
    steps: Array<{ step_number: number; action: string; input_data: string; expected_result: string }>;
    expected_results: string[];
    priority: "P0" | "P1" | "P2" | "P3";
    dimensions: string[];
    created_at: string;
  };
  new_version: {
    version: number;
    title: string;
    preconditions: string[];
    steps: Array<{ step_number: number; action: string; input_data: string; expected_result: string }>;
    expected_results: string[];
    priority: "P0" | "P1" | "P2" | "P3";
    dimensions: string[];
    modification_reason: string | null;
    created_at: string;
  };
  change_summary: string;   // AI 生成的变更摘要
}
```

#### 错误处理

| 状态码 | 处理策略 |
| :--- | :--- |
| 400 | v1/v2 参数无效 |
| 404 | 用例或指定版本不存在 |
| 500 | message.error("获取版本对比失败") |

**前端处理**：获取 old_version 和 new_version 后，使用 jsdiff 库的 `diffWords`/`diffLines` 对比各字段，渲染 VersionDiffView。

---

## 新增 Service 文件

### notificationAPI.ts

```typescript
// services/notificationAPI.ts
import apiClient from './apiClient';

const notificationAPI = {
  /** 获取未读数（轮询） */
  getUnreadCount: () =>
    apiClient.get<UnreadCountResponse>('/notifications/unread-count'),

  /** 获取通知列表 */
  getNotifications: (params?: { page?: number; per_page?: number; read?: boolean }) =>
    apiClient.get<NotificationListResponse>('/notifications', { params }),

  /** 标记单条已读 */
  markAsRead: (notificationId: string) =>
    apiClient.patch<MarkReadResponse>(`/notifications/${notificationId}/read`),

  /** 全部已读 */
  markAllAsRead: () =>
    apiClient.post<MarkAllReadResponse>('/notifications/mark-all-read'),
};

export default notificationAPI;
```

### caseAPI.ts

```typescript
// services/caseAPI.ts
import apiClient from './apiClient';

const caseAPI = {
  /** 获取系统用例树 */
  getCaseTree: (systemId: string, params?: { batch_status?: string }) =>
    apiClient.get<CaseTreeResponse>(`/systems/${systemId}/case-tree`, { params }),

  /** 全局搜索 */
  searchCases: (params: {
    keyword: string;
    system_id?: string;
    priority?: string;
    review_status?: string;
    trust_level?: number;
    page?: number;
    per_page?: number;
  }) =>
    apiClient.get<SearchResponse>('/cases/search', { params }),

  /** 获取用例版本列表（第二段） */
  getCaseVersions: (caseId: string) =>
    apiClient.get<CaseVersionsResponse>(`/cases/${caseId}/versions`),

  /** 获取版本对比数据（第二段） */
  getCaseDiff: (caseId: string, v1: number, v2: number) =>
    apiClient.get<CaseDiffResponse>(`/cases/${caseId}/diff`, { params: { v1, v2 } }),
};

export default caseAPI;
```

---

## batchAPI.ts 扩展

```typescript
// services/batchAPI.ts（新增方法）

/** 获取系统批次列表 */
getSystemBatches: (systemId: string, params?: PaginationParams & { status?: string }) =>
  apiClient.get<SystemBatchListResponse>(`/systems/${systemId}/batches`, { params }),

/** 批次重试 */
retryBatch: (batchId: string, fromStage?: PipelineStage) =>
  apiClient.post<RetryBatchResponse>(`/batches/${batchId}/retry`, { from_stage: fromStage }),

/** 获取批次下拉选项 */
getBatchOptions: (params: { system_id: string; status?: string }) =>
  apiClient.get<BatchOptionsResponse>('/batches/options', { params }),
```

---

## systemAPI.ts 扩展

```typescript
// services/systemAPI.ts（新增方法）

/** 获取系统下拉选项 */
getSystemOptions: () =>
  apiClient.get<SystemOptionsResponse>('/systems/options'),
```

---

## 错误处理策略增强

### 新增错误处理模式

| 模式 | 适用场景 | 实现方式 |
| :--- | :--- | :--- |
| 静默失败 | 轮询请求（通知未读数） | catch 中仅 console.warn，不展示 UI 提示 |
| 乐观更新 | 标记已读、全部已读 | 先更新本地状态，请求失败时回滚 |
| 重试按钮 | 树加载失败、批次重试失败 | EmptyState 组件内嵌"重试"操作 |
| 降级保持 | 搜索失败 | 保持上次成功的搜索结果，展示错误提示条 |

### 乐观更新实现示例

```typescript
// notificationStore 中标记已读的乐观更新
markAsRead: async (notificationId: string) => {
  const prev = get().notifications;
  const prevCount = get().unreadCount;

  // 乐观更新
  set({
    notifications: prev.map(n =>
      n.id === notificationId ? { ...n, read: true } : n
    ),
    unreadCount: Math.max(0, prevCount - 1),
  });

  try {
    await notificationAPI.markAsRead(notificationId);
  } catch (error) {
    // 回滚
    set({ notifications: prev, unreadCount: prevCount });
    console.error('标记已读失败', error);
  }
},
```

---

## 轮询约定变更

### 新增：通知未读数轮询

| 配置项 | 值 |
| :--- | :--- |
| 轮询接口 | `GET /api/v1/notifications/unread-count` |
| 轮询间隔 | 10000ms（10 秒） |
| 启动条件 | AppLayout 挂载（用户登录后） |
| 终止条件 | 用户登出或页面卸载 |
| 错误处理 | 静默失败，不计数连续失败 |
| 页面隐藏 | 暂停轮询（visibilitychange API） |
| 页面可见 | 立即执行一次 + 恢复轮询 |

### 变更：用例生成进度轮询

| 配置项 | 原值 | 新值 | 说明 |
| :--- | :--- | :--- | :--- |
| 轮询间隔 | 5000ms | 5000ms | 不变 |
| 页面隐藏处理 | 未定义 | 暂停轮询 | 新增：visibilitychange 暂停 |
| 页面可见恢复 | 未定义 | 立即轮询一次 | 新增：恢复时立即刷新 |

---

## API 调用完整清单（变更后）

| 编号 | 方法 | 路径 | Service 文件 | 变更类型 |
| :--- | :--- | :--- | :--- | :--- |
| 2.1 | POST | /systems | systemAPI.ts | 保持 |
| 2.2 | GET | /systems | systemAPI.ts | 保持 |
| 2.3 | GET | /systems/:id | systemAPI.ts | 保持 |
| 2.4 | PUT | /systems/:id | systemAPI.ts | 保持 |
| 2.5 | DELETE | /systems/:id | systemAPI.ts | 保持 |
| 2.6 | POST | /systems/:id/associations | systemAPI.ts | 保持 |
| 2.7 | GET | /systems/:id/associations | systemAPI.ts | 保持 |
| 2.8 | DELETE | /systems/:id/associations/:assocId | systemAPI.ts | 保持 |
| 2.9 | POST | /systems/:id/documents/batch | documentAPI.ts | 保持 |
| 2.10 | GET | /systems/:id/documents | documentAPI.ts | 保持 |
| 2.11 | GET | /documents/:id | documentAPI.ts | 保持 |
| 2.12 | DELETE | /documents/:id | documentAPI.ts | 保持 |
| 2.13 | POST | /documents/:id/associations | documentAPI.ts | 保持 |
| 2.14 | GET | /documents/:id/associations | documentAPI.ts | 保持 |
| 2.15 | POST | /documents/:id/generate | batchAPI.ts | 保持 |
| 2.16 | GET | /batches/:id | batchAPI.ts | 保持 |
| 2.17 | POST | /batches/:id/clarify | batchAPI.ts | 保持 |
| 2.18 | POST | /batches/:id/iterate | batchAPI.ts | 保持 |
| 2.19 | POST | /batches/:id/archive | batchAPI.ts | 保持 |
| 2.20 | PATCH | /testcases/:id/review | batchAPI.ts | 保持 |
| 2.21 | POST | /exports | exportAPI.ts | 保持 |
| 2.22 | GET | /exports/:id | exportAPI.ts | 保持 |
| 2.23 | GET | /exports | exportAPI.ts | 保持 |
| **2.24** | **GET** | **/systems/:id/batches** | **batchAPI.ts** | **新增** |
| **2.25** | **GET** | **/systems/:id/case-tree** | **caseAPI.ts** | **新增** |
| **2.26** | **GET** | **/notifications/unread-count** | **notificationAPI.ts** | **新增** |
| **2.27** | **GET** | **/notifications** | **notificationAPI.ts** | **新增** |
| **2.28** | **PATCH** | **/notifications/:id/read** | **notificationAPI.ts** | **新增** |
| **2.29** | **POST** | **/notifications/mark-all-read** | **notificationAPI.ts** | **新增** |
| **2.30** | **GET** | **/cases/search** | **caseAPI.ts** | **新增** |
| **2.31** | **POST** | **/batches/:id/retry** | **batchAPI.ts** | **新增** |
| **2.32** | **GET** | **/batches/options** | **batchAPI.ts** | **新增** |
| **2.33** | **GET** | **/systems/options** | **systemAPI.ts** | **新增** |
| **2.34** | **GET** | **/cases/:id/versions** | **caseAPI.ts** | **新增（第二段）** |
| **2.35** | **GET** | **/cases/:id/diff** | **caseAPI.ts** | **新增（第二段）** |
