# UI重启后无LLM页面巡检

## Goal

在不访问公司 LLM 网关、不触发真实生成的前提下，复核重启后本地基础设施、API、worker、前端和核心页面入口是否仍可用，为周一真实小批次验收降低环境和页面层风险。

本任务只补“运行环境和页面入口证据”，不替代真实小批次、首次使用平台 QA 演练或 `.audit` 审查。

## Requirements

- R1：启动或复核 Docker infra、API、worker、frontend，确认访问的是当前工作区最新代码。
- R2：只做只读页面/API 巡检，不上传文件、不触发生成、不调用 LLM。
- R3：覆盖至少这些入口：系统列表、知识库、批次页、用例资产、搜索、导出。
- R4：记录服务状态、页面访问结果、发现的问题和是否影响周一真实验收。
- R5：不得修改 `src/testcase_generator/**`，不得改变平台 API/前端代码。
- R6：产物必须包含批判性 review，说明本轮证据能证明什么、不能证明什么。

## Acceptance Criteria

- [x] API / worker / frontend 状态有命令证据。
- [x] 核心页面入口巡检有记录，且明确是否触发 LLM。
- [x] 报告说明本轮结果是否改变“候选交付，等待真实小批次验收”的结论。
- [x] 自审记录指出证据边界，不能把本轮 smoke test 夸大成真实验收。
- [x] `src/testcase_generator/**` 无 diff。

## Notes

- 当前已知状态：Docker infra 和 worker 在线；API / frontend 端口未启动。
