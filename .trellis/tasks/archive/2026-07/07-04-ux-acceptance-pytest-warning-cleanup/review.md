# UI 验收测试输出告警清理自审

## 结论

本次清理成立。`collect_ignore_glob` 在当前 pytest 版本下是未知 ini 选项，导致每次运行 UI 预检脚本单测都有配置告警。移除它可以让验收工具链测试输出更可靠。

## 自审问题

### 1. 是否会扩大测试收集范围

不会。`pyproject.toml` 仍保留 `testpaths = ["tests"]`，pytest 只从 `tests/` 收集测试；移除无效的 `collect_ignore_glob` 不会改变当前实际收集路径。

### 2. 是否属于 UI/UX 目标范围

属于验收工具链质量，不是 UI 页面功能本身。它的价值是让 `tests/test_ux_acceptance_preflight.py` 的输出更干净，避免周一或后续回归时把无关 warning 当成风险。

### 3. 是否影响主流程或生成核心

不影响。只修改 pytest 配置和 Trellis 文档，没有修改前端、API、worker 或 `src/testcase_generator/**`。

## 判定

可以收口。后续如需忽略非 tests 目录，应使用当前 pytest 支持的机制或 conftest 变量，而不是无效 ini 配置。
