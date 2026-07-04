# API 路由模式（后端）

> 本文件只记录代码里**真实存在**的写法，每条都带 `文件:行号` 锚点。
> 写新接口时照抄此模板即可与现有代码对齐。

---

## 分层与目录

固定四层，新接口按此摆放：

| 层 | 目录 | 职责 | 真实示例 |
|----|------|------|----------|
| 路由 | `src/platform_api/api/v1/<模块>.py` | 解析入参、依赖注入、调 Service、包装响应 | `api/v1/systems.py` |
| 入参/出参模型 | `src/platform_api/schemas/<模块>.py` | Pydantic 请求/响应模型 | `schemas/batch.py` |
| 业务 | `src/platform_api/services/<模块>_service.py` | 业务逻辑、抛 `ApiError` | `services/system_service.py` |
| 数据访问 | `src/platform_api/repositories/` | `BaseRepository(session, Model)` CRUD | `repositories/base.py` |

> 路由层**不直接写 SQL/业务规则**，只编排；业务规则放 Service。

---

## 路由文件骨架

每个模块一个 `APIRouter(tags=[...])`（中文 tag），路径里自带资源前缀（如 `/systems`、`/batches`）：

```python
# src/platform_api/api/v1/batches.py:27
router = APIRouter(tags=["批次管理"])
```

注册链（两级）：模块 router → `v1_router`（带 `/api/v1` 前缀）→ `app`：

```python
# src/platform_api/api/v1/__init__.py:17
v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(systems_router)
v1_router.include_router(batches_router)
# ...
```

```python
# src/platform_api/main.py:45
app.include_router(v1_router)
```

**新增模块清单**：建 `api/v1/<模块>.py` → 在 `api/v1/__init__.py` 导入并 `include_router`。

---

## 依赖注入（DI）

只有两种合法形态，二选一：

1. 直接注入 session（路由内简单逻辑）：

```python
# src/platform_api/api/v1/batches.py:54
async def trigger_generation(
    document_id: UUID,
    body: GenerateRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
```

2. 注入 Service（推荐，Service 工厂函数下划线开头）：

```python
# src/platform_api/api/v1/systems.py:22
def _get_service(session: AsyncSession = Depends(get_session)) -> SystemService:
    return SystemService(session)

@router.get("/systems")
async def list_systems(
    service: SystemService = Depends(_get_service),
):
```

> 会话生命周期由 `core/database.py:73` 的 `get_session` 统一管理：成功 `commit`、异常 `rollback`。路由里**不要手动 commit**。

---

## 入参约定

- 路径参数：强类型，UUID 用 `UUID`（`batch_id: UUID`）。
- 分页：`page: int = Query(1, ge=1)`、`per_page: int = Query(20, ge=1, le=100)`。
- 可选过滤：`status: str | None = Query(None, description="按状态过滤")`。
- 请求体：来自 `schemas/`，如 `body: ClarificationRequest`；可选体用 `Body | None = None`。
- 分页列表必须在 Service 查询里写确定性 `order_by(...)`，不要依赖数据库默认顺序。常规后台列表优先 `created_at.desc()`，并用 `id.desc()` 做同时间兜底；否则同一页内容可能漂移，测试夹具也可能被真实历史数据挤出当前页。

```python
# src/platform_api/api/v1/batches.py:82
async def list_batches(
    status: str | None = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: BatchListService = Depends(_get_batch_list_service),
):
```

```python
# src/platform_api/services/system_service.py:70
stmt = (
    select(...)
    .outerjoin(...)
    .order_by(System.created_at.desc(), System.id.desc())
    .offset(offset)
    .limit(limit)
)
```

---

## 出参约定：统一响应信封

**所有成功响应**必须经 `core/response.py` 包装，不要直接返回裸 dict / ORM 对象。

- 单对象/普通数据：`return success(data)` → `{"code":0,"message":"success","data":...}`
- 分页列表：先建 `PaginationParams`，再 `success(paginated_response(items, total, params))`

```python
# src/platform_api/core/response.py:55
def success(data: Any = None) -> dict:
    return {"code": 0, "message": "success", "data": data}
```

```python
# src/platform_api/api/v1/batches.py:90
params = PaginationParams(page=page, per_page=per_page)
items, total = await service.list_all(status=status, page=page, per_page=per_page)
return success(paginated_response(items, total, params))
```

分页结构固定为 `{items, total, page, per_page, total_pages}`（`core/response.py:44`）。

---

## 异步/长任务：202 + Celery 派发

LLM/流水线类长任务**不在 HTTP 请求里执行**，派给 Celery，立即返回 `202`：

```python
# src/platform_api/api/v1/batches.py:227
@router.post("/batches/{batch_id}/iterate", status_code=202)
async def trigger_iterate(...):
    celery_app.send_task(
        "testcase_generator.iterate_batch",
        kwargs={...},
        queue="testcase_generation",
    )
    return JSONResponse(status_code=202, content=success({...}))
```

`status_code=202` 在装饰器与 `JSONResponse` 两处都写。

---

## 错误处理：抛 `ApiError`，不要手拼错误响应

业务错误一律 `raise ApiError("<错误码>", "<中文消息>")`，由全局处理器渲染。错误码表是唯一来源（`core/exceptions.py:12`）。

```python
# src/platform_api/api/v1/batches.py:66
if doc is None:
    raise ApiError("E4041", "文档不存在")
```

常用错误码：

| 码 | HTTP | 含义 |
|----|------|------|
| `E4001` | 400 | 请求参数无效 / 状态不允许 |
| `E4041` | 404 | 资源不存在 |
| `E4091` | 409 | 资源状态冲突（如有关联数据无法删除） |
| `E4221` | 422 | 数据验证失败 |
| `E5001` | 500 | 服务内部错误（未捕获异常兜底） |

错误响应结构由处理器统一渲染为 `{error_code, message, request_id}`（`core/exceptions.py:40`）。`request_id` 由 `main.py:30` 中间件注入，路由层无需关心。

---

## Service 层写法（路由的下游）

```python
# src/platform_api/services/system_service.py:20
class SystemService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = BaseRepository(session, System)

    async def get_system(self, system_id: UUID) -> System:
        system = await self.repo.get_by_id(system_id)
        if system is None:
            raise ApiError("E4041", "系统不存在")
        return system
```

要点：构造只收 `session`；用 `BaseRepository`；找不到/冲突时抛 `ApiError`；唯一性/外键冲突捕获 `IntegrityError` 转 `ApiError`（见 `system_service.py:70`）。

---

## 场景：历史文档类型重标注

### 1. Scope / Trigger

- Trigger: 前端需要修正历史 `other` 文档的业务类型，新增跨层接口 `PATCH /api/v1/documents/{document_id}/type`。
- 范围只允许更新 `knowledge.documents.doc_type`；不得重跑解析、重建向量、触发生成批次或改写文档内容。

### 2. Signatures

- Request schema: `UpdateDocumentTypeRequest.doc_type: str`（`src/platform_api/schemas/document.py:69`）。
- Route: `@router.patch("/{document_id}/type")`（`src/platform_api/api/v1/documents.py:81`）。
- Service: `DocumentService.update_document_type(document_id: UUID, doc_type: str) -> Document`（`src/platform_api/services/document_service.py:157`）。

### 3. Contracts

- URL: `PATCH /api/v1/documents/{document_id}/type`
- Body: `{"doc_type": "<DOC_TYPES value>"}`
- Allowed values: `DOC_TYPES = tuple(item.value for item in DocType)`（`src/platform_api/schemas/document.py:12`）
- Success: 统一信封 `{"code":0,"message":"success","data":<Document>}`，其中 `data.doc_type` 为更新后的值。
- Commit: 路由不手动 commit；仍由 `get_session` 生命周期统一提交。

### 4. Validation & Error Matrix

| 条件 | 行为 |
|------|------|
| `doc_type not in DOC_TYPES` | `ApiError("E4001", "无效的文档类型...")` |
| `document_id` 不存在 | 复用 `get_document`，返回 `E4041` |
| 文档已软删除 | 复用 `get_document`，返回 `E4041` |

### 5. Good/Base/Bad Cases

- Good: 历史 `other` 文档重标注为 `prd` / `tech_doc` / `test_rule`，返回更新后的文档详情。
- Base: 已是非 `other` 的文档也允许重标注，便于人工纠错。
- Bad: 不要根据标题、路径或正文自动猜类型并批量迁移；误分类会污染生成依据。

### 6. Tests Required

- Service 成功用例：断言返回对象和数据库里的 `doc_type` 都已更新。
- Service 错误用例：非法类型返回 `E4001`；软删除或不存在返回 `E4041`。
- HTTP 契约用例：用 `httpx.ASGITransport` 调 `PATCH /api/v1/documents/{id}/type`，断言响应信封和 `data.doc_type`。

### 7. Wrong vs Correct

#### Wrong

```python
# 不要做自动推断或连带重解析
doc.doc_type = infer_type_from_title_or_content(doc)
trigger_kb_parsing([doc])
```

#### Correct

```python
if doc_type not in DOC_TYPES:
    raise ApiError("E4001", f"无效的文档类型，允许值：{DOC_TYPES}")
doc = await self.get_document(document_id)
doc.doc_type = str(doc_type)
await self.session.flush()
```

---

## ⚠️ 已知空白：无鉴权层

当前 `src/platform_api` **没有任何认证/授权**：所有 `Depends(...)` 只有 `get_session` 与 `_get_*_service`，无 `current_user` / JWT / `Security`，`pyproject.toml` 无鉴权依赖，`settings.py` 无 `SECRET_KEY`。

→ 因此本仓库**没有"鉴权检查"的既有模式可抄**。若 next feature 需要登录/权限，必须先单独做鉴权设计（新增 PRD/设计），不要凭空在路由里写 auth 依赖。
