# Docker生产部署与内网服务化设计

## Architecture

生产部署使用一个独立 compose 文件：

```text
公司内网浏览器
  -> Windows服务器IP:3000
      -> web(Nginx)
          -> 静态前端资源
          -> /api/ 反向代理到 api:8000
              -> postgres:5432
              -> redis:6379
              -> minio:9000
              -> worker 通过 Redis 消费生成任务
```

## Compose Boundaries

- `docker-compose.infra.yml`: 开发模式。仅基础设施进 Docker，API/worker/前端仍在宿主机运行。端口映射保留但绑定到 `127.0.0.1`。
- `docker-compose.prod.yml`: 内网服务器模式。API、worker、web、Postgres、Redis、MinIO 全部进 Docker，只暴露 `3000`。

## Images

- 后端镜像：基于 Python 3.12 slim，安装 `uv`，复制源码、`pyproject.toml`、`uv.lock`、alembic 配置和迁移文件。API 与 worker 使用同一镜像，不同 command。
- 前端镜像：Node 阶段构建 React/Vite 静态资源，Nginx 阶段提供静态资源和反向代理。

## Configuration

- 生产配置通过 `.env.prod` 注入，不提交真实 key。
- 容器内地址使用 Docker 服务名：
  - `DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/qa_platforms`
  - `REDIS_URL=redis://redis:6379/0`
  - `CELERY_BROKER_URL=redis://redis:6379/1`
  - `CELERY_RESULT_BACKEND=redis://redis:6379/2`
  - `MINIO_ENDPOINT=minio:9000`
- 对外入口只有 `web` 服务的 `3000:80`。

## Startup and Migration

- Postgres、Redis、MinIO 配 healthcheck。
- API 启动前执行 `alembic upgrade head`，然后启动 uvicorn。
- Worker 依赖 Postgres、Redis、MinIO 健康后启动 Celery。
- 所有长期服务使用 `restart: unless-stopped`。

## Backup

- 备份脚本通过 `docker compose -f docker-compose.prod.yml exec` 执行：
  - `pg_dump` 导出数据库。
  - `mc mirror` 或等效 MinIO 客户端导出 bucket 对象。
- 备份输出到宿主机 `backups/<timestamp>/`，便于复制到移动硬盘或公司共享盘。

## Rollback

- 代码层面：切回 `main` 或回滚本分支 commit。
- 运行层面：`docker compose -f docker-compose.prod.yml down` 停掉生产栈；volume 默认保留。
- 数据层面：不自动删除 volume；备份/恢复单独手动执行。

## Trade-offs

- 不暴露 MinIO Console 会牺牲一点手工排查便利，但明显降低内网误访问风险。
- API 启动时自动跑迁移简化部署，但如果迁移失败，API 容器会重启并在日志中暴露失败原因；这是比静默使用旧 schema 更安全的行为。
- 开发 compose 仍保留本机端口映射，因为 API/worker 不在容器里时必须通过宿主机端口访问依赖。
