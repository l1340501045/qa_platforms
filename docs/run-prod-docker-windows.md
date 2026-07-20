# Windows 内网服务器 Docker 生产部署指南

本文用于把一台闲置 Windows 笔记本部署成公司内网 QA 平台服务器。部署后同事只需要访问：

```text
http://<Windows服务器IP>:3000
```

## 部署形态

```text
浏览器 -> Windows:3000 -> web(Nginx)
                      -> /api/ -> api:8000
                                  -> postgres:5432
                                  -> redis:6379
                                  -> minio:9000
                                  -> worker
```

生产 compose 只暴露 `3000`。Postgres、Redis、MinIO 不映射宿主机端口，只在 Docker 内网通信。

## 机器准备

1. 安装 Docker Desktop。
2. Docker Desktop 设置中启用：
   - `Use the WSL 2 based engine`
   - `Start Docker Desktop when you sign in`
3. 安装 Git。
4. 拉取代码：

```powershell
git clone https://github.com/l1340501045/qa_platforms.git
cd qa_platforms
git checkout main
```

## 配置生产环境变量

```powershell
copy .env.prod.example .env.prod
notepad .env.prod
```

首次部署至少填写：

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

视觉、校验和向量模型可以先沿用主网关，启动后再到“系统设置 → AI 模型设置”逐项拆分。页面保存的 API Key 会使用 `MODEL_CONFIG_ENCRYPTION_KEY` 加密，API 与 worker 必须配置相同值。该密钥必须随 `.env.prod` 一起安全备份，启用后不要随意更换；丢失后历史模型 Key 无法解密。

可在 PowerShell 生成 Fernet 密钥，把输出完整复制到 `.env.prod`：

```powershell
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$rng.Dispose()
[Convert]::ToBase64String($bytes).Replace('+','-').Replace('/','_')
```

如果暂时不配置该密钥，旧环境变量仍能运行，每次处理开始时读取当时的环境配置，但模型设置页会禁用保存。向量模型输出维度固定为 `1024`。

不要把 `.env.prod` 提交到 Git。

## 启动

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

启动后检查：

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
curl http://127.0.0.1:3000/health
```

如果本机健康检查通过，同事访问：

```text
http://<Windows服务器IP>:3000
```

## Windows 防火墙

如果同事访问不了，管理员 PowerShell 执行：

```powershell
New-NetFirewallRule -DisplayName "QA Platform Web 3000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3000 -Profile Domain,Private
```

不要开放 `5432`、`6379`、`9000`、`9001`。

## 开机/登录自启

管理员或当前用户 PowerShell 执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\register-qa-platform-startup.ps1
```

这会注册一个 Windows 计划任务：登录后自动执行生产 compose 启动脚本。

同时必须在 Docker Desktop 中开启 `Start Docker Desktop when you sign in`。

说明：Docker Desktop 个人版通常随用户登录启动，不是传统 Windows 后台服务。闲置笔记本当服务器时，建议保持服务器账号登录状态，或由公司 IT 配置自动登录/受管服务模式。

## 停止

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\stop-qa-platform-prod.ps1
```

只停止容器，不删除数据库和文件 volume。

## 升级

```powershell
git pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

API 容器启动时会自动执行 `alembic upgrade head`。

升级后同时重启 API 与 worker，确保两者加载同一个 `MODEL_CONFIG_ENCRYPTION_KEY`。当前正在执行的处理继续使用启动时已经加载的版本；升级或保存后才启动的新任务、继续、重试、迭代和重新生成使用最新配置。

## 日志

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f web
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f api
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f worker
```

真实跑批卡住时优先看 `worker` 日志。

## 备份

在 Git Bash、WSL 或 macOS/Linux shell 中执行：

```bash
./scripts/backup_prod.sh
```

备份输出：

```text
backups/<时间戳>/
  postgres.sql
  minio/qa-documents/
  metadata.txt
```

建议把 `backups/` 定期复制到移动硬盘或公司共享盘。

## 恢复

恢复会覆盖数据库对象和 MinIO 文件。恢复前建议先停掉入口和业务进程，保留数据库/Redis/MinIO：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml stop web api worker
```

确认后执行：

```bash
CONFIRM_RESTORE=1 ./scripts/restore_prod_backup.sh <时间戳>
```

例如：

```bash
CONFIRM_RESTORE=1 ./scripts/restore_prod_backup.sh 20260706-183000
```

恢复完成后重新启动：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

## 为什么生产模式不映射数据库/Redis/MinIO端口

Docker 容器之间不需要宿主机端口映射。API 访问依赖服务时用 Docker 内网地址：

```text
postgres:5432
redis:6379
minio:9000
```

宿主机端口映射只用于“让 Docker 外部的人访问容器”。生产环境里公司同事只需要访问前端入口 `3000`，所以只映射 `3000`。

## 常见问题

### Docker Desktop 里看不到 5432/6379/9000 端口是不是异常？

不是。生产模式下这是正确现象。

### MinIO 控制台还能打开吗？

生产模式默认不能从浏览器打开。这样做是为了避免对象存储后台暴露给公司内网。需要排查文件时优先通过平台页面和备份脚本处理。

### 需要重置全部数据怎么办？

谨慎执行：

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml down -v
```

这会删除数据库、Redis、MinIO volume。执行前必须先备份。
