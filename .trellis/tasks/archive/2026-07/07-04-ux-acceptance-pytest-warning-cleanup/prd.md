# UI验收测试输出告警清理

## Goal

清理 `uv run pytest tests/test_ux_acceptance_preflight.py` 输出中的 pytest 配置告警，让 UI/UX 验收工具链的测试结果更干净，避免真实失败被无关 warning 干扰。

## Confirmed Facts

- 新增预检脚本测试通过，但 pytest 输出 `PytestConfigWarning: Unknown config option: collect_ignore_glob`。
- `collect_ignore_glob` 不是当前 pytest 版本支持的 `pyproject.toml` ini 选项。
- 当前 `pyproject.toml` 已设置 `testpaths = ["tests"]`，pytest 默认只收集 `tests/`，不需要用 `collect_ignore_glob = ["src/*"]` 避免收集 `src`。

## Requirements

- R1：移除无效 pytest 配置项，消除目标单测输出告警。
- R2：保留 `testpaths = ["tests"]`，不扩大测试收集范围。
- R3：修改不能触碰前端、API、worker 或 `src/testcase_generator/**`。

## Out of Scope

- 不调整 pytest 版本。
- 不调整测试目录结构。
- 不运行完整全量测试。

## Acceptance Criteria

- [x] `uv run pytest tests/test_ux_acceptance_preflight.py` 通过且不再出现 `Unknown config option: collect_ignore_glob`。
- [x] `uv run python scripts/ux_acceptance_preflight.py --skip-runtime --allow-dirty` 通过。
- [x] `src/testcase_generator/**` 无 diff。
- [x] 自审记录说明移除配置不会扩大测试收集范围。
