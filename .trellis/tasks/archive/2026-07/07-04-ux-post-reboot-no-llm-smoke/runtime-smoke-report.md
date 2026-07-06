# UI 重启后无 LLM 页面巡检报告

## 结论

本轮在不上传文件、不触发生成、不访问 LLM 网关的前提下，复核了本地基础设施、API、worker、frontend 和 8 个核心页面入口。结果支持一个有限结论：

**UI/UX 分支在重启后仍可进入真实小规模验收；但本轮不能替代真实跑批、首次使用平台 QA 演练或新 `.audit` 审查。**

## 环境

- 分支：`feat/qa-platform-ux-modernization`
- Docker infra：Postgres / Redis / MinIO 均在线
- API：`127.0.0.1:8000`，进程 `./.venv/bin/python -m uvicorn src.platform_api.main:app --host 0.0.0.0 --port 8000`
- Frontend：`127.0.0.1:3000`，进程 `node .../web/node_modules/.bin/vite --host 127.0.0.1 --port 3000`
- Worker：`celery@LaceyMac: OK pong`
- 巡检方式：内置浏览器 + Playwright 只读 DOM 检查

## 运行态预检

首次完整预检在任务文件未提交时按设计失败：

```text
[FAIL] 工作区状态: M .trellis/tasks/07-04-qa-platform-ux-modernization/task.json
处理建议: 先提交或处理未提交改动，避免真实验收结果无法追溯到固定代码版本。
```

带 `--allow-dirty` 复核运行态与配置时通过：

```text
[PASS] 当前分支: feat/qa-platform-ux-modernization
[PASS] 工作区状态: 存在未提交改动，但已通过 --allow-dirty 放行
[PASS] 生成核心 diff: src/testcase_generator 无变更
[PASS] 验收资料: docs/acceptance 资料齐全
[PASS] .env 配置: 真实跑批模型配置符合 runbook
[PASS] 生成配置: existence_merge_enabled=True, split_cap_enabled=True, cases_per_tp_cap=4, p0_quota_enabled=False
[PASS] API: HTTP 200 {"status":"ok","version":"0.1.0"}
[PASS] Frontend: HTTP 200
[PASS] Worker: ->  celery@LaceyMac: OK
```

## 1280 宽页面巡检

| 页面 | URL | 关键结果 |
|---|---|---|
| 系统列表 | `/systems` | 20 行系统，系统总数 106，无横向溢出，console warning/error 为空 |
| 知识库 | `/systems/6b0ea53c-f734-4bc9-8506-663d47107b9d/documents` | 上传类型默认 PRD，树存在且仅 3 个节点，文档列表 1 行，无横向溢出 |
| 文档详情 | `/documents/effbf86d-3719-4010-b2b9-b8a66c925b80` | 能看到修改类型、知识速查表、生成测试用例等入口，无横向溢出 |
| 审核中心 | `/review` | 待处理队列、状态筛选和批次列表可见，20 行表格，无横向溢出 |
| 批次工作台 | `/batches/6f30e1bd-89ad-4e98-878c-4b48014eb1a4` | 2680 用例批次可打开；树 16 个可见节点、展开节点 2 个，未默认全展开 |
| 用例资产 | `/case-library` | 主集候选资产 1852 条；树 15 个可见节点、展开节点 2 个，未默认全展开 |
| 用例搜索 | `/search` | 空态清晰，引导输入关键词或浏览用例资产，无横向溢出 |
| 导出中心 | `/exports` | 2 条导出任务、2 个可下载文件，无横向溢出 |

8 个页面均无 `.ant-spin-spinning` 持续加载；`tab.dev.logs({ levels: ["warn", "error"] })` 为空。

## 1024 宽页面巡检

同一组 8 个页面在 `1024x720` viewport 下复核，页面级 `documentElement.scrollWidth > clientWidth + 2` 均为 `false`。

关键树表页面：

- 批次工作台：树 16 个可见节点，表格 20 行，无横向溢出。
- 用例资产：树 15 个可见节点，表格 20 行，无横向溢出。
- 知识库：树 3 个可见节点，表格 1 行，无横向溢出。

## 发现与风险

### 1. 历史漫剧 PRD 仍显示为 `其他`

知识库和文档详情中，历史文档 `漫剧批创初版功能PRD` 仍显示文档类型为 `其他`。这不是本轮新上传链路的失败证据，而是旧数据在文档类型修复前已入库。

影响：

- 不阻塞本轮只读巡检。
- 周一真实验收必须按 runbook 新上传 `docs/acceptance/ux-small-batch-prd.md`，选择 `PRD`，并确认新文档显示为 `PRD`。
- 如果只看旧漫剧文档，会误以为上传类型修复未生效。

### 2. 页面文本中出现“失败”不等于错误态

审核中心、用例资产、导出中心页面文本中包含“失败”状态筛选或“失败 0”等业务状态，因此粗略文本扫描会命中 error-like 关键词。但浏览器 console warning/error 为空，页面没有运行错误。

## 判定

- 可以继续按 `docs/acceptance/runbook.md` 进入真实小规模批次验收。
- 不改变父任务结论：当前仍是 UI/UX 候选交付，不能直接合 main。
- 真实验收前仍需保持工作区干净；否则 `ux_acceptance_preflight.py` 会按设计阻止跑批。
