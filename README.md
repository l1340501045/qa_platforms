# QA Platforms

AI 驱动的 QA 智能测试平台，支持 PRD/技术文档上传、知识库解析、测试用例生成、审核、检索和导出。

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
