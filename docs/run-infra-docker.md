# Docker 基础设施运行指南

本文件是本机开发模式：只把基础设施放进 Docker，API、worker、前端仍在宿主机使用最新源码启动。

如果要把 Windows 笔记本作为公司内网服务器，请使用生产部署文档：[Windows 内网服务器 Docker 生产部署指南](./run-prod-docker-windows.md)。

本机开发模式端口只绑定 `127.0.0.1`：

- Postgres + pgvector：`127.0.0.1:5434`
- Redis / Celery broker：`127.0.0.1:6380`
- MinIO：`127.0.0.1:9100`，控制台 `127.0.0.1:9101`

后端 API 和 Celery worker 继续在本机用 `uv run ...` 启动。这样真实跑批一定使用当前工作区的最新代码，不会被旧 Docker 镜像卡住。
由于 API/worker 在 Docker 外，本机开发模式必须保留这些端口映射；但绑定到 `127.0.0.1` 后，公司内网不能直接访问这些依赖端口。

## 首次启动全新基础设施

先启动 Docker Desktop，确认 Docker Engine 已运行。

如果当前没有占用 `5434` / `6380` / `9100` / `9101` 的旧容器：

```bash
docker compose -f docker-compose.infra.yml up -d
uv run alembic upgrade head
```

`minio-init` 会自动创建 `qa-documents` bucket。

## 已有旧容器时

当前这台机器上曾经跑过依赖容器，且库里已有历史数据。为了保留历史数据，可以直接启动旧容器：

```bash
docker start qa-platforms-pg qa-workbench-redis-1 qa-workbench-minio-1
uv run alembic upgrade head
```

如果明确想切到新的 compose 管理的空白基础设施，先停掉占用端口的旧容器，再启动 compose：

```bash
docker stop qa-platforms-pg qa-workbench-redis-1 qa-workbench-minio-1
docker compose -f docker-compose.infra.yml up -d
uv run alembic upgrade head
```

不要删除旧容器或 volume，除非确认不需要历史批次和已上传文档。

## 启动最新代码

基础设施启动后，后端和 worker 在本机启动：

```bash
uv run uvicorn src.platform_api.main:app --reload --port 8000
uv run celery -A src.platform_api.core.celery_app worker -Q testcase_generation,kb_parsing,export --loglevel=info
```

真实跑批依赖 Celery worker。只启动 API 不够。

如需在页面保存四类模型配置，先在 `.env` 中设置 `MODEL_CONFIG_ENCRYPTION_KEY`。API 与 worker 必须使用同一个值：

```bash
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

把输出写入 `.env` 后重启 API 与 worker，再打开“系统设置 → AI 模型设置”。不配置时旧环境变量仍可继续使用，每次处理开始时读取当时的环境配置，但页面会禁用保存。向量模型连接测试要求输出维度固定为 `1024`。

## 健康检查

```bash
nc -zv 127.0.0.1 5434
nc -zv 127.0.0.1 6380
curl -I http://127.0.0.1:9100/minio/health/live
curl http://127.0.0.1:8000/health
uv run celery -A src.platform_api.core.celery_app.celery_app inspect ping --timeout=3
```

最后一条必须有 worker 回复，才适合开始真实跑批。
