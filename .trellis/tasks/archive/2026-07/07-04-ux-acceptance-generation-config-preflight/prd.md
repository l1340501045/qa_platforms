# UI验收预检覆盖生成配置

## Goal

把真实跑批关键生成配置纳入 `scripts/ux_acceptance_preflight.py`，让周一执行 `--skip-runtime` 静态预检时就能发现 `existence_merge_enabled`、`split_cap_enabled`、`cases_per_tp_cap`、`p0_quota_enabled` 等配置漂移。

## Confirmed Facts

- `docs/acceptance/runbook.md` 第 2 节已经要求手工检查模型配置和生成配置。
- 当前预检脚本只检查 `.env` 模型配置，没有检查前端触发生成配置。
- 当前真实跑批配置要求：
  - `existence_merge_enabled=True`
  - `split_cap_enabled=True`
  - `cases_per_tp_cap=4`
  - `p0_quota_enabled=False`
- 前端触发批次时通过 `web/src/services/batchApi.ts` 的 `BEST_PRACTICE_GENERATION_CONFIG` 显式传入配置。
- 后端默认配置存在于 `src/platform_api/core/settings.py`，pipeline 契约配置存在于 `src/testcase_generator/pipeline/config.py`。

## Requirements

- R1：预检脚本必须只读检查生成配置，不 import 业务模块、不启动服务、不写数据库。
- R2：预检脚本至少检查前端 `BEST_PRACTICE_GENERATION_CONFIG` 是否包含真实跑批关键配置。
- R3：预检脚本应同步检查后端默认 settings 和 pipeline 契约配置，避免三处配置漂移。
- R4：runbook / evidence ledger 应说明完整预检已经覆盖模型配置和生成配置，人工 `rg` 仅作为排障手段。
- R5：不得修改 `src/testcase_generator/**` 生成核心逻辑。

## Out of Scope

- 不调整真实生成策略。
- 不修改前端触发生成配置。
- 不修改平台 API 或 worker 行为。
- 不启动服务，不跑真实批次。

## Acceptance Criteria

- [x] `ux_acceptance_preflight.py --skip-runtime` 输出包含生成配置检查项。
- [x] 若生成配置与期望不符，预检失败并提示修复方向。
- [x] `uv run python scripts/ux_acceptance_preflight.py --skip-runtime --allow-dirty` 通过。
- [x] `uv run ruff check scripts/ux_acceptance_preflight.py` 通过。
- [x] `python3 -m py_compile scripts/ux_acceptance_preflight.py` 通过。
- [x] 自审记录说明本次只增加只读预检，不改变生成逻辑。
