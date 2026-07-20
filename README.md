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

3. 编辑 `.env.prod`，首次部署至少填入主模型网关，并配置模型设置加密密钥：

```text
LLM_BASE_URL=公司LLM网关地址
LLM_API_KEY=真实key
LLM_PRIMARY_MODEL=claude-opus-4-6
LLM_VISION_MODEL=claude-opus-4-6
LLM_VERIFY_MODEL=deepseek-v4-pro-office
OPENAI_EMBEDDING_MODEL=公司向量模型名称
MODEL_CONFIG_ENCRYPTION_KEY=Fernet密钥
LLM_CONCURRENCY=8
```

视觉、校验和向量模型可以先沿用主网关，服务启动后再到“系统设置 → AI 模型设置”逐项拆分。`MODEL_CONFIG_ENCRYPTION_KEY` 用于加密页面保存的 API Key，API 与 worker 必须使用同一个值；可在 macOS、Linux 或 WSL 中生成：

```bash
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
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

## AI 模型设置

启动平台后，可在“系统设置 → AI 模型设置”统一配置全平台使用的四类 OpenAI 兼容模型：

- 生成模型：负责需求理解和测试用例生成。
- 视觉模型：只处理图片和视觉内容。
- 校验模型：负责结构化复核与质量校验。
- 向量模型：负责知识库向量化，输出维度固定为 `1024`，维度不匹配时不会启用。

每张配置卡都独立填写网关地址、API Key 和模型名称。API Key 不会回显；输入框留空表示继续使用已保存的 Key。保存时后端会再次执行真实连接测试，只有测试通过才会生成一个新的不可变配置版本并启用。

每次模型处理真正开始执行时读取当前有效版本，并在这一次执行结束前固定使用它。因此，保存配置不会让当前正在执行的处理突然换模型；保存后才启动或重新执行的新任务、继续、重试、迭代、重新生成和解析会使用最新版本。页面不提供历史版本或回滚入口，历史仅保留在后端。

如果尚未配置 `MODEL_CONFIG_ENCRYPTION_KEY`，旧环境变量仍可继续运行现有流程，每次处理开始时会读取当时的环境配置，但页面会禁用保存。配置密钥并重启 API 与 worker 后即可从页面保存；同一套部署中的所有 API、worker 实例必须保持该值一致。密钥启用后必须随部署配置安全备份，不要随意更换或丢失，否则历史版本中的 API Key 将无法解密。

## 安全边界

当前系统没有登录鉴权层，模型设置页也没有单独权限控制，只适合在可信公司内网使用。当前部署使用 HTTP，不要直接暴露到公网；如需公网或非可信网络访问，必须先补充 HTTPS 与登录鉴权。
