# 测试模式（后端）

> 本文件记录仓库**真实存在**的两类测试写法。新功能照对应模板写即可。

---

## pytest 全局约定

配置在 `pyproject.toml:56`：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
```

- `asyncio_mode = "auto"`：异步测试直接 `async def test_xxx()`，**无需** `@pytest.mark.asyncio` 装饰器（部分老用例仍带着，可保留但非必需）。
- 测试目录镜像 `src/` 结构：`tests/platform_api/`、`tests/testcase_generator/`、`tests/knowledge_base/`。
- 命名 `test_*.py`；集成测试惯例后缀 `_integration.py`。

运行命令（来自 `CLAUDE.md`）：

```bash
uv run pytest                                   # 全量
uv run pytest tests/platform_api/test_xxx.py    # 单文件
uv run pytest -k "test_dedup"                   # 按名匹配
```

---

## 模式 A：DB 集成测试（真实 PostgreSQL，不 mock）

适用：Service 层逻辑、DB 触发器、约束、事务行为。

**入口守卫**：DB 不可达自动 skip，不会让无 DB 环境红。`conftest.py` 提供 `requires_db`（socket 探测 `localhost:5434`）和 autouse 的 `reset_db_engine_per_test`：

```python
# tests/platform_api/conftest.py:24
requires_db = pytest.mark.skipif(
    not _db_reachable(),
    reason="需 PostgreSQL (localhost:5434)，当前环境不可达",
)
```

文件顶部统一挂守卫：

```python
# tests/platform_api/test_notification_integration.py:19
pytestmark = requires_db
```

**真实 session fixture** + **裸 SQL 播种/清理**（用 `sqlalchemy.text()`，yield 后清理）：

```python
# tests/platform_api/test_notification_integration.py:32
@pytest.fixture
async def db_session():
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()

@pytest.fixture
async def seed_batch(db_session: AsyncSession):
    # INSERT ... ON CONFLICT DO NOTHING 播种 system/document/batch
    await db_session.execute(text("INSERT INTO public.systems (id, name) VALUES (:id, :name) ..."), {...})
    await db_session.commit()
    yield {...}
    # DELETE 清理
    await db_session.execute(text("DELETE FROM ... WHERE id = :id"), {...})
    await db_session.commit()
```

**断言**：直接实例化 Service 调方法，或裸 SQL 查回验证：

```python
# tests/platform_api/test_notification_integration.py:210
service = NotificationService(db_session)
items, total = await service.list_notifications(page=1, per_page=10)
assert total >= 2
```

---

## 模式 B：HTTP 契约测试（httpx ASGI，进程内打 app）

适用：验证响应信封、错误结构、路由形状、路径不被路径参数遮蔽等"接口契约"。

用 `httpx.ASGITransport(app=app)` 直接进程内打 FastAPI app（不起服务器、无需网络）：

```python
# tests/platform_api/test_contract_conformance.py:11
from httpx import AsyncClient, ASGITransport
from src.platform_api.main import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

测试函数注入 `client` 发请求并断言信封：

```python
# tests/platform_api/test_contract_conformance.py:31
async def test_success_response_envelope(client: AsyncClient):
    resp = await client.get("/health")
    # 断言 {code, message, data} / {error_code, message, request_id} 结构
```

同款见 `tests/platform_api/test_cheat_sheets_api.py:33`（含 404 错误结构、批量操作）。

---

## 选型速查

| 你要测… | 用模式 | 需要 DB？ |
|---------|--------|-----------|
| Service 业务逻辑 / DB 触发器 / 约束 | A（DB 集成） | 是（不可达则 skip） |
| 响应信封 / 错误码 / 路由契约 | B（httpx ASGI） | 否（除非该端点查库） |
| 纯函数 / 算法（如去重、字数） | 直接单测，无 fixture | 否 |

> 两类都遵守：异步直接 `async def`、DB 集成挂 `pytestmark = requires_db`、播种数据测试后清理干净。
