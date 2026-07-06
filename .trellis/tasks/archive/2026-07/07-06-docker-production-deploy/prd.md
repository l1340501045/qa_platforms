# Docker生产部署与内网服务化

## Goal

把当前 QA 平台从“开发机分别启动基础设施、API、worker、前端”的形态，补齐为可在一台 Windows 笔记本服务器上长期运行的 Docker 部署形态。公司内网用户只访问一个入口地址，平台主流程包括上传 PRD、解析、生成用例、查看/导出用例都必须继续可用。

## Background

- 当前 `docker-compose.infra.yml` 只启动 Postgres、Redis、MinIO，API、Celery worker、前端仍在宿主机启动。
- 当前基础设施 compose 暴露了 `5434`、`6380`、`9100`、`9101`，Docker Desktop 中能看到端口映射；这适合本机开发，但不适合作为公司内网服务器。
- 前端代码请求 `/api/v1`，Vite 开发模式用代理转发到 `localhost:8000`；生产部署需要由单一入口反向代理 API。
- 用户希望 Windows 闲置笔记本作为内网服务器，并且主流程不能被部署改造阻断。

## Requirements

- R1: 新增生产 Docker 编排，包含前端入口、API、Celery worker、Postgres、Redis、MinIO。
- R2: 生产部署只暴露宿主机端口 `3000`，公司内网用户通过 `http://<Windows服务器IP>:3000` 访问。
- R3: 生产部署不得把 Postgres、Redis、MinIO API、MinIO Console 暴露到宿主机或公司内网；容器间通过 Docker 内网服务名访问。
- R4: API 和 worker 必须使用同一份最新代码镜像，避免 worker 与 API 版本漂移。
- R5: 前端生产构建必须通过 Nginx 提供静态资源，并把 `/api/` 反向代理到 API 容器。
- R6: 服务应具备自动重启能力，适合 Windows Docker Desktop 重启后恢复运行。
- R7: 提供备份脚本，至少覆盖 Postgres 数据和 MinIO 文档对象，并说明恢复边界。
- R8: 提供 Windows 开机自启/运维说明，让非技术用户能知道如何启动、停止、查看日志、备份。
- R9: 保留现有开发模式，不让本机开发因为生产部署改造而断掉；开发模式的端口映射应限制为本机可访问。
- R10: 项目根目录提供 README，第一屏能指引内网服务器部署，并链接详细部署文档。

## Acceptance Criteria

- [ ] 存在生产 compose 文件，且只有前端入口服务包含宿主机 `ports` 映射到 `3000`。
- [ ] 生产 compose 中 Postgres、Redis、MinIO 不包含宿主机端口映射。
- [ ] API、worker、前端镜像构建文件齐全，生产 compose 可以从仓库源码构建。
- [ ] Nginx 配置支持前端路由回退和 `/api/` 反向代理。
- [ ] 生产环境变量示例说明 Docker 内网地址，例如 `postgres:5432`、`redis:6379`、`minio:9000`。
- [ ] 开发基础设施 compose 的端口绑定收紧到 `127.0.0.1`，避免被公司内网直接访问。
- [ ] 备份脚本不依赖宿主机直接访问数据库/MinIO端口，使用 `docker compose exec` 或容器内命令完成。
- [ ] 文档包含 Windows Docker Desktop 开机自启、部署、升级、备份、恢复、健康检查和常见故障处理。
- [ ] 项目根目录 README 包含生产部署快速开始、端口暴露原则、备份入口和详细文档链接。
- [ ] 本次改造不改变测试用例生成业务逻辑。

## Out of Scope

- 不引入 Kubernetes、云服务器、域名、HTTPS 证书或公司级 SSO。
- 不迁移已有本机开发数据库数据到新 Windows 服务器；只提供部署后的备份/恢复机制。
- 不把 `.env` 中的真实 LLM key 提交到仓库。
