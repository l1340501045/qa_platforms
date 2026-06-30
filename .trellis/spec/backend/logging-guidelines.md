# 日志规范（后端）

> 本文件记录**真实存在**的日志写法 + 明确的空白点。当前日志覆盖很窄，请勿照搬"理想化的结构化日志"——那在本仓库不存在。

---

## 现状一句话

只有 **Celery 任务层** 和 **全局异常处理器** 打日志；路由层、Service 层基本不打日志；没有集中日志配置，沿用 uvicorn/root logger 默认。

---

## 既有写法（可照抄）

模块级 logger，标准库 `logging`：

```python
# src/platform_api/tasks/export_task.py:19
import logging
logger = logging.getLogger(__name__)
```

实际用到的级别与场景：

| 级别 | 用法 | 真实示例 |
|------|------|----------|
| `logger.info(...)` | 任务开始/完成、关键节点 | `tasks/tg_integration.py:47`、`tasks/kb_integration.py:60` |
| `logger.warning(...)` | 可恢复异常/降级 | `tasks/kb_integration.py:48` |
| `logger.exception(...)` | 任务失败（自动带堆栈） | `tasks/export_task.py:170`、`tasks/kb_integration.py:65` |
| `logger.error(..., exc_info=True)` | 未捕获异常兜底（带堆栈） | `core/exceptions.py:54` |

参数用 `%s` 惰性占位，不要 f-string 拼接：

```python
# src/platform_api/tasks/kb_integration.py:60
logger.info("KB parse triggered for document %s", document_id)
```

未捕获异常的统一兜底（全局处理器，已注册于 `main.py:41`）：

```python
# src/platform_api/core/exceptions.py:54
logger.error("Unhandled exception: %s: %s", type(exc).__name__, exc, exc_info=True)
```

---

## 请求关联：`request_id`

HTTP 链路靠 `request_id` 关联，但它**只进响应、未进日志**：

- `main.py:30` 中间件为每个请求生成 `request_id`，写入 `request.state.request_id` 和响应头 `X-Request-ID`。
- 错误响应体里带 `request_id`（`core/exceptions.py:47`）。
- 前端请求也会自带 `X-Request-ID`（`web/src/services/api.ts:23`）。

---

## ⚠️ 已知空白（写新代码时心里有数，别假设它们存在）

- **无集中配置**：没有 `logging.config.dictConfig` / `basicConfig`，`settings.py` 无 `LOG_LEVEL`。级别/格式由运行环境（uvicorn）决定。
- **无结构化日志**：没有 `structlog`/JSON 日志，全是纯文本 `%s`。
- **路由/Service 层不打日志**：业务错误走 `ApiError` 异常链，不在 Service 里 `logger.xxx`。
- **`request_id` 未绑进日志记录**：日志行里没有 request_id 字段，无法直接按请求串联日志。

→ 新功能若沿用现状：仅在 **Celery 任务**里按上表打 `info/exception`；HTTP 错误交给 `ApiError` + 全局处理器，不要在路由里手写日志。若确实需要更强的可观测性（结构化/集中配置/request_id 入日志），那是一次独立改造，不在"照抄现有模式"范围内。
