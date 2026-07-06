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

## 团队协同开发流程

团队协作时，`main` 代表可部署主线。不要直接在 `main` 上做非平凡开发，所有功能、修复、UI/UX 调整、数据库迁移和部署改造都先开独立分支。

### 1. 开始一个新需求

先同步主线：

```bash
git switch main
git pull origin main
```

再开工作分支：

```bash
git switch -c feat/你的功能名
```

推荐分支名前缀：

- `feat/...`: 新功能
- `fix/...`: bug 修复
- `docs/...`: 文档
- `chore/...`: 配置、脚本、依赖、部署杂项
- `test/...`: 测试补充

### 2. 本地开发和验证

开发前先按“本机开发启动”跑起环境。改动完成后，至少跑受影响范围的验证：

```bash
npm --prefix web run build
uv run pytest tests/platform_api
```

如果只改文档，可以不跑完整测试，但要确认文档命令和路径没有写错。

### 3. 提交代码

一个 commit 只表达一个清晰成果。不要用 `git add .`，只精确暂存本次相关文件：

```bash
git status --short
git add README.md docs/run-prod-docker-windows.md
git diff --cached --name-status
git commit -m "docs(协作): 补充团队开发流程"
```

commit message 使用中文，建议格式：

```text
feat(模块): 中文说明
fix(模块): 中文说明
docs(模块): 中文说明
chore(模块): 中文说明
test(模块): 中文说明
```

### 4. 合并回 main

小团队可以本地验证通过后合并：

```bash
git switch main
git pull origin main
git merge --ff-only 你的分支名
git push origin main
```

如果 `--ff-only` 失败，说明 `main` 有新提交或存在分叉，不要硬推。先处理冲突或改走 Pull Request。

多人并行开发时推荐走 Pull Request：

```bash
git push origin 你的分支名
```

PR 描述至少写清楚：

- 改了什么
- 怎么验证
- 是否影响主流程
- 如何回滚

### 5. 部署到内网服务器

`main` 推到远端后，在 Windows 服务器上执行：

```powershell
git pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

部署后检查：

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
curl http://127.0.0.1:3000/health
```

### 6. 协作注意事项

- 不提交 `.env`、`.env.prod`、日志、备份、运行产物。
- 涉及数据库迁移、生成流程、导出格式、部署脚本的改动，必须在提交说明里写清风险和验证结果。
- UI/UX 改动要附截图或说明访问页面。
- 主流程是上传文档、生成用例、审核、导出；任何改动都不能无验证地破坏这条链路。
- 生产服务器改动前先备份：`./scripts/backup_prod.sh`。

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
