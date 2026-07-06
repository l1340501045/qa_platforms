# UI验收预检脚本测试补强

## Goal

为 `scripts/ux_acceptance_preflight.py` 的生成配置解析和失败判定补充轻量单测，防止前端/后端配置结构变化后预检静默漏检。

## Confirmed Facts

- 预检脚本已经新增生成配置检查，会解析：
  - `web/src/services/batchApi.ts`
  - `src/testcase_generator/pipeline/config.py`
  - `src/platform_api/core/settings.py`
- 这些解析逻辑依赖轻量字符串、AST 和正则，后续代码结构变化时有回归风险。
- 项目目前没有专门的 scripts 测试目录，但 pytest 可以直接收集 `tests/test_*.py`。

## Requirements

- R1：新增测试必须直接覆盖前端、pipeline、settings 三类配置解析。
- R2：新增测试必须覆盖配置不一致时 `check_generation_config()` 返回失败。
- R3：测试不能启动服务、不能访问数据库、不能触发生成。
- R4：不得修改前端、API、worker 或 `src/testcase_generator/**` 生成核心逻辑。

## Out of Scope

- 不新增真实跑批测试。
- 不新增浏览器测试。
- 不修改预检脚本行为，除非测试暴露真实缺陷。

## Acceptance Criteria

- [x] `tests/test_ux_acceptance_preflight.py` 存在。
- [x] `uv run pytest tests/test_ux_acceptance_preflight.py` 通过。
- [x] `uv run ruff check scripts/ux_acceptance_preflight.py tests/test_ux_acceptance_preflight.py` 通过。
- [x] `uv run python scripts/ux_acceptance_preflight.py --skip-runtime --allow-dirty` 通过。
- [x] 自审记录说明测试没有扩展到真实服务或生成逻辑。
