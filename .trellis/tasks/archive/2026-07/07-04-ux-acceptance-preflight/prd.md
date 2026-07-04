# UI验收前预检脚本

## 目标

把真实跑批前的分支、工作区、生成核心 diff、模型配置、基础服务健康检查做成只读预检脚本，降低周一验收摩擦。

## 背景

`docs/acceptance/runbook.md` 已经列出周一真实验收前要做的手工检查。当前风险是用户回到公司网络后才发现：

- 分支或工作区状态不对。
- UI/UX 分支误混入 `src/testcase_generator/**` 变更。
- `.env` 模型配置不是真实跑批目标配置。
- API / frontend / worker 没启动或启动错。
- 验收资料文件缺失。

这些问题都不需要等真实 LLM 批次开始后才发现，适合做成只读 preflight。

## 要求

- 新增一个命令行脚本，默认只读检查，不创建系统、不上传文档、不触发生成、不写数据库。
- 检查当前分支、工作区是否干净。
- 检查 `checkpoint/architecture-migration-pre-ux...HEAD` 下 `src/testcase_generator/**` 是否无 diff。
- 检查 `docs/acceptance/README.md`、`runbook.md`、`post-batch-report-template.md`、`ux-small-batch-prd.md` 是否存在。
- 检查 `.env` 中真实跑批模型配置是否符合 runbook：
  - `LLM_PRIMARY_MODEL=claude-opus-4-6`
  - `LLM_VISION_MODEL=claude-opus-4-6`
  - `LLM_VERIFY_MODEL=deepseek-v4-pro-office`
  - `LLM_CONCURRENCY=8`
- 检查 API、frontend、worker 是否可用，并允许通过参数跳过运行态检查，方便在服务未启动前先做静态检查。
- 输出要用中文，能明确告诉用户下一步该修什么。
- 更新 `docs/acceptance/runbook.md`，把脚本作为可选但推荐的快速预检入口。
- 补充 `review.md`，批判性说明脚本能证明什么、不能证明什么。

## 不做

- 不改后端业务逻辑。
- 不改 `src/testcase_generator/**`。
- 不替代真实小规模跑批。
- 不替代首次使用平台的 QA 任务演练。
- 不自动启动服务，不自动修改 `.env`。

## 验收标准

- `uv run python scripts/ux_acceptance_preflight.py --skip-runtime` 能在当前仓库执行并给出静态检查结果。
- 脚本在工作区干净、验收资料存在、生成核心无 diff 时通过对应检查。
- 运行态检查失败时，脚本输出明确失败项，而不是抛出难懂 traceback。
- `docs/acceptance/runbook.md` 包含推荐命令。
- `review.md` 明确指出：preflight 只能降低跑批前误操作风险，不能证明 UI/UX 已可合 main。
