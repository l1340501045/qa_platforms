# Docker生产部署与内网服务化实现计划

## Checklist

1. 读取相关后端、前端和部署规范。
2. 新增后端 Dockerfile 和启动入口，支持 API/worker 共享镜像。
3. 新增前端 Dockerfile 和 Nginx 配置，支持 `/api/` 代理和 SPA 回退。
4. 新增 `docker-compose.prod.yml`，只暴露 `3000`。
5. 新增 `.env.prod.example`，使用 Docker 内网服务名。
6. 收紧 `docker-compose.infra.yml` 开发端口为 `127.0.0.1` 绑定。
7. 新增备份脚本和 Windows 启动脚本/说明。
8. 新增部署文档，覆盖启动、升级、备份、恢复、日志、健康检查。
9. 验证 compose 配置、前端构建、后端关键测试或静态检查。
10. 自审端口暴露、主流程风险和回滚方式。

## Validation Commands

```bash
docker compose -f docker-compose.prod.yml config
docker compose -f docker-compose.infra.yml config
npm --prefix web run build
uv run pytest tests/platform_api/test_export_download.py tests/platform_api/test_export_split.py tests/test_ux_acceptance_preflight.py
```

如本机 Docker 构建可用，补充：

```bash
docker compose -f docker-compose.prod.yml build
```

## Risky Files

- `docker-compose.infra.yml`: 只能收紧开发端口绑定，不能破坏现有本机开发。
- `.env.example` / `.env.prod.example`: 不允许提交真实 key。
- Nginx 代理配置：必须保证 `/api/v1` 请求仍能到达 API。

## Rollback Point

本任务在 `codex/docker-production-deploy` 分支开发。若部署方案不合适，直接丢弃该分支即可，不影响 `main`。
