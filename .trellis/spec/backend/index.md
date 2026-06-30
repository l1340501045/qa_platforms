# 后端开发规范

> 仓库后端真实模式索引。技术栈：FastAPI + SQLAlchemy(async) + Celery + PostgreSQL。
> 原则：只记录代码里**真实存在**的写法，每条带 `文件:行号` 锚点；写实不写理想。

---

## 规范索引

| 文件 | 内容 | 状态 |
|------|------|------|
| [API 路由模式](./api-route-pattern.md) | 分层、路由注册、DI、入参、响应信封、202、`ApiError` 错误码 | ✅ 已填（code-backed） |
| [日志规范](./logging-guidelines.md) | 既有日志写法 + 明确空白点 | ✅ 已填（窄范围如实） |
| [测试模式](./testing-pattern.md) | DB 集成测试 + httpx ASGI 契约测试两套模板 | ✅ 已填（code-backed） |
| [目录结构](./directory-structure.md) | 模块组织与文件布局 | ⬜ 占位（部分已并入 API 路由模式） |
| [数据库规范](./database-guidelines.md) | ORM / 查询 / 迁移 | ⬜ 占位（未在本次 bootstrap 范围） |
| [错误处理](./error-handling.md) | 错误类型与处理策略 | ⬜ 占位（核心约定见 API 路由模式） |
| [质量规范](./quality-guidelines.md) | 代码标准、禁用模式 | ⬜ 占位（未在本次 bootstrap 范围） |

> 本次 bootstrap 聚焦"next feature 高频要用"的四类模式：API 路由、日志、测试、前端表单（见 `../frontend/form-pattern.md`）。其余占位文件留待按需填充。

---

## ⚠️ 已知空白：无鉴权层（重要）

经核查，`src/platform_api` **没有任何认证/授权**：

- 路由所有 `Depends(...)` 仅 `get_session` 与 `_get_*_service`，无 `current_user` / JWT / `Security`。
- `pyproject.toml` 无任何鉴权库；`settings.py` 无 `SECRET_KEY` / token 配置。
- 代码中出现的 `permission` / `token` 均属"测试用例生成业务维度"，**与 API 鉴权无关**。

→ 因此本仓库**没有"鉴权检查"的既有模式可抄**。若后续功能涉及登录/权限/数据权限，需作为独立设计任务先行，不要在路由里凭空添加 auth 依赖。

---

## 语言约定

按项目根 `CLAUDE.md`：所有文档与代码注释使用**中文**。本目录 spec 同此约定。
