# QA Platforms 

AI 驱动的 QA 智能测试平台，支持 PRD/技术文档上传、知识库解析、测试用例生成、审核、检索和导出。

## AI 直接部署指令（Docker Desktop）

如果目标是“把整个项目直接部署到 Docker Desktop 上运行”，AI 必须使用生产 Docker 编排：

```text
docker-compose.prod.yml
```

不要使用 `docker-compose.infra.yml` 做整站部署；它只适合本机开发，只启动 Postgres、Redis、MinIO 这些基础设施。

### 部署目标

- 运行位置：Docker Desktop。
- 部署形态：web、api、worker、Postgres、Redis、MinIO 全部运行在 Docker 容器中。
- 对外入口：只暴露前端端口 `3000`。
- 浏览器访问：
  - 本机访问：`http://127.0.0.1:3000`
  - 内网访问：`http://<部署机器IP>:3000`

### 数据库和依赖怎么部署

AI 不需要单独安装数据库，也不需要让用户手工建库建表。生产 compose 会自动启动这些容器：

| 容器服务 | 作用 | Docker 内网地址 | 是否暴露给同事 |
|---|---|---|---|
| `postgres` | PostgreSQL + pgvector 数据库 | `postgres:5432` | 不暴露 |
| `redis` | Celery 队列和结果缓存 | `redis:6379` | 不暴露 |
| `minio` | 上传文档、导出文件等对象存储 | `minio:9000` | 不暴露 |
| `api` | 后端接口，并在启动时自动执行数据库迁移 | `api:8000` | 只通过 web 反向代理访问 |
| `worker` | 后台解析、生成、导出任务 | Docker 内网 | 不暴露 |
| `web` | 前端页面和 Nginx 入口 | 宿主机 `3000` | 暴露 |

数据库初始化规则：

- `docker-compose.prod.yml` 会创建 `postgres` 容器。
- `.env.prod` 中的 `POSTGRES_DB=qa_platforms` 会让 PostgreSQL 首次启动时创建业务库。
- `api` 容器启动时会自动执行 `alembic upgrade head`，创建或升级表结构。
- `minio-init` 容器会自动创建 `MINIO_BUCKET=qa-documents`。
- 数据库、Redis、MinIO 数据保存在 Docker volume 中：`prod_pgdata`、`prod_redisdata`、`prod_miniodata`。
- 只要不执行 `docker compose down -v`，重启或升级容器不会清空数据。

### AI 执行顺序

1. 确认 Docker Desktop 已启动。
2. 在项目根目录复制生产环境变量文件：

```powershell
copy .env.prod.example .env.prod
```

macOS / Linux / WSL 可用：

```bash
cp .env.prod.example .env.prod
```

3. 编辑 `.env.prod`，必须填入真实 LLM 网关配置：

```text
LLM_BASE_URL=公司LLM网关地址
LLM_API_KEY=真实key
LLM_PRIMARY_MODEL=claude-opus-4-6
LLM_VISION_MODEL=claude-opus-4-6
LLM_VERIFY_MODEL=deepseek-v4-pro-office
LLM_CONCURRENCY=8
```

4. 保持 `.env.prod` 中 Docker 内网地址不变：

```text
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=qa_platforms
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/qa_platforms
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=qa-documents
MINIO_SECURE=false
```

5. 构建并启动完整服务：

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

6. 验证部署：

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
curl http://127.0.0.1:3000/health
```

`ps` 中至少要看到 `postgres`、`redis`、`minio`、`api`、`worker`、`web` 正常运行；`api` 健康后，同事就可以直接打开：

```text
http://<部署机器IP>:3000
```

### AI 不要做的事

- 不要把 `.env.prod` 提交到 Git。
- 不要把 Postgres、Redis、MinIO 端口暴露到宿主机或公司内网。
- 不要为了生产部署启动 `docker-compose.infra.yml`。
- 不要手动进入数据库建表；API 容器启动时会自动执行迁移。
- 不要执行 `docker compose down -v`，除非用户明确要求清空全部数据且已经备份。

## 内网服务器部署（推荐给团队使用）

如果要把一台 Windows 笔记本作为公司内网服务器，让同事通过浏览器访问，使用生产 Docker 部署：

```powershell
git clone https://github.com/l1340501045/qa_platforms.git
cd qa_platforms
copy .env.prod.example .env.prod
notepad .env.prod
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

启动后访问：

```text
http://<Windows服务器IP>:3000
```

生产部署只暴露宿主机端口 `3000`。Postgres、Redis、MinIO 不暴露到 Windows 或公司内网，只在 Docker 内网中被 API/worker 访问。

详细部署、开机自启、备份和恢复说明见：

- [Windows 内网服务器 Docker 生产部署指南](docs/run-prod-docker-windows.md)

Windows 笔记本长期运行时，建议开启 Docker Desktop 的登录自启，并注册项目自启脚本；详见上面的部署指南。

## 本机开发启动

本机开发推荐只把基础设施放进 Docker，API、worker、前端仍使用当前工作区源码启动。

```bash
docker compose -f docker-compose.infra.yml up -d
uv sync
uv run alembic upgrade head
./scripts/start_platform_services.sh
cd web
npm ci
npm run dev -- --host 0.0.0.0 --port 3000
```

开发模式基础设施端口只绑定 `127.0.0.1`：

- Postgres: `127.0.0.1:5434`
- Redis: `127.0.0.1:6380`
- MinIO: `127.0.0.1:9100`
- MinIO Console: `127.0.0.1:9101`

详细说明见：

- [Docker 基础设施运行指南](docs/run-infra-docker.md)

## 关键运维命令

生产模式查看状态：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
curl http://127.0.0.1:3000/health
```

生产模式查看日志：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f api
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f worker
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f web
```

生产模式备份：

```bash
./scripts/backup_prod.sh
```

## 配置文件

- `.env.example`: 本机开发环境变量示例。
- `.env.prod.example`: 生产 Docker 环境变量示例。
- `.env` / `.env.prod`: 本地真实配置，已被 `.gitignore` 排除，不能提交。

## 安全边界

当前系统没有登录鉴权层，适合在可信公司内网使用。不要直接暴露到公网。
