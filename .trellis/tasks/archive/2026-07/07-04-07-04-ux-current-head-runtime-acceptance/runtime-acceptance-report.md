# 当前 HEAD UI/UX 运行态验收报告

## 结论

当前 `feat/qa-platform-ux-modernization` 最新代码已经通过轻量运行态验收，可以进入用户验收 / PR review 准备阶段。

这次验收补齐了父任务最终审查里最大的证据缺口：浏览器证据已经更新到当前 HEAD，并覆盖了历史文档类型重标注、系统列表真实统计、核心页面信息架构和窄屏布局。

但仍不建议直接宣称“可以无条件合入 main”。原因是：本轮没有跑新的真实 LLM 批次，没有做审查确认/需修改/删除等破坏性 mutation，也没有让未参与开发的 QA 按脚本完成第一次上手演练。

## 用户口径校准

本轮 UI/UX 判断口径不是“新手 QA 教程”，而是：

> 面向具备 QA 背景、但第一次使用本平台的人。页面应让 TA 清楚当前页面负责什么、主流程下一步在哪里、状态是否可继续。

这意味着页面不需要解释 QA 是什么，也不应该做成营销页；它应该像一个专业 QA 工作台，把上传资料、发起生成、处理批次、审查、资产沉淀、搜索和导出串成可理解的工作流。

## 服务状态

| 检查项 | 结果 |
|---|---|
| Docker infra | Postgres / Redis / MinIO 已可用 |
| API health | `curl http://127.0.0.1:8000/health` -> `{"status":"ok","version":"0.1.0"}` |
| Frontend | `curl -I http://127.0.0.1:3000` -> `HTTP/1.1 200 OK` |
| Worker | `celery@LaceyMac: OK pong` |

## 验收数据

| 对象 | 值 |
|---|---|
| 系统 | `漫剧批创系统` |
| system_id | `6b0ea53c-f734-4bc9-8506-663d47107b9d` |
| 文档 | `漫剧批创初版功能PRD` |
| document_id | `effbf86d-3719-4010-b2b9-b8a66c925b80` |
| 文档类型 | `other`，可通过 UI 人工标注 |
| 批次 | `6f30e1bd-89ad-4e98-878c-4b48014eb1a4` |
| 批次状态 | `pending_review` |
| 用例总数 | `2680` |

## 浏览器巡检

### 1280 宽度

| 页面 | 关键断言 | 横向溢出 | 控制台错误/告警 |
|---|---|---|---|
| `/systems` | 项目入口、系统统计、真实文档数/批次数可见 | 无 | 0 |
| `/systems/:systemId/documents` | 知识库、上传资料、生成批次、进入审查可见 | 无 | 0 |
| `/documents/:documentId?from=knowledge&system_id=:systemId` | 返回知识库、修改类型、生成测试用例可见 | 无 | 0 |
| `/review?status=pending_review` | 工作台、待处理批次、待审核队列可见 | 无 | 0 |
| `/batches/:batchId?from=review&status=pending_review` | 返回工作台、生成与审查、用例总数 2680 可见 | 无 | 0 |
| `/case-library` | 用例资产、系统筛选、资产说明可见 | 无 | 0 |
| `/search?q=CBO&system_id=:systemId` | 全局搜索、关键词、结果统计可见 | 无 | 0 |
| `/exports` | 导出中心、新建导出、任务统计可见 | 无 | 0 |

### 1024 宽度

复用同一浏览器标签页设置 1024x720 后巡检同一组页面，避免新标签页不继承视口导致误判。

| 页面 | 关键断言 | 横向溢出 | 控制台错误/告警 |
|---|---|---|---|
| `/systems` | 项目/系统、系统总数、当前页文档数、当前页批次数可见 | 无 | 0 |
| `/systems/:systemId/documents` | 知识库、上传资料、生成批次、进入审查可见 | 无 | 0 |
| `/documents/:documentId?from=knowledge&system_id=:systemId` | 文档详情、返回知识库、修改类型可见 | 无 | 0 |
| `/review?status=pending_review` | 工作台、待处理批次、待审核可见 | 无 | 0 |
| `/batches/:batchId?from=review&status=pending_review` | 生成与审查、用例总数、2680 可见 | 无 | 0 |
| `/case-library` | 用例资产、系统可见 | 无 | 0 |
| `/search?q=CBO&system_id=:systemId` | 全局搜索、CBO 可见 | 无 | 0 |
| `/exports` | 导出中心、新建导出可见 | 无 | 0 |

## 本轮发现并修复的问题

### 问题

打开文档详情页“修改类型”弹窗时，浏览器控制台出现 Ant Design 表单告警：

`Instance created by useForm is not connected to any Form element`

根因是页面在 Modal/Form 挂载前调用 `typeForm.setFieldsValue(...)`。在 `destroyOnHidden` 场景下，这会让 form instance 短暂处于未连接状态。

### 修复

| 文件 | 修复 |
|---|---|
| `web/src/pages/DocumentDetail/index.tsx` | 移除打开弹窗前的 `setFieldsValue`，改为 Form `initialValues` + 随文档变化的 `key` |
| `web/src/pages/Knowledge/index.tsx` | 移除历史文档标注弹窗打开前的 `setFieldsValue`，同样改为 `initialValues` + 稳定 `key` |

修复后复测：

| 弹窗 | 操作 | 结果 |
|---|---|---|
| 文档详情 `修改类型` | 打开弹窗 | 弹窗文案可见，无横向溢出，控制台错误/告警 0 |
| 知识库 `标注类型` | 打开弹窗 | 默认选中 PRD，风险说明可见，无横向溢出，控制台错误/告警 0 |

## 门禁命令

| 命令 | 结果 |
|---|---|
| `npm run lint` | 通过 |
| `npm run typecheck` | 通过 |
| `npm run build` | 通过，仍有既有 Vite large chunk warning |

## 批判性自审

### 1. 当前是否符合“第一次使用本平台的 QA 能知道该干嘛”

阶段性符合。核心页面都已经把页面职责和下一步动作放在首屏或主工作区：

- 项目/系统：先选系统，再进入知识库上传或查看批次。
- 知识库：上传资料、生成批次、进入审查三步明确。
- 文档详情：先确认资料状态和关联资产，再生成。
- 工作台：先处理待澄清、失败、待审核和生成中队列。
- 批次页：围绕生成状态、阶段进度、审查列表和落库动作组织。
- 用例资产、搜索、导出：分别服务沉淀、定位和交付。

但这仍是专家审查结论，不等于真实 QA 首次上手结论。合 main 前最好让一个未参与开发的 QA 只拿一个任务目标走一遍，不提前讲解。

### 2. 当前是否保护完整生成测试用例主流程

是。本任务没有修改 `src/testcase_generator/**`，没有更改生成算法、LLM 配置、worker pipeline 或 case convergence 策略。

本次浏览器验收只证明“旧批次与现有数据在最新 UI 下可浏览、可进入、可审查”，不能证明“公司网关下新跑批次稳定产出高质量用例”。

### 3. 是否还有明显 UI/UX 债务

还有，但不是阻塞主流程的债务：

- `npm run build` 仍提示大 chunk，需要后续做路由级或组件级拆包。
- 没有做真实文件上传 mutation、真实生成 mutation、真实审查 mutation，本轮只验证入口和只读浏览。
- “第一次上手”仍缺真实用户任务脚本验证。

### 4. 是否建议现在合入 main

建议不要马上直接合入 main。更稳的顺序是：

1. 当前分支提交并归档运行态验收任务。
2. 在公司网络可访问 LLM 网关时，跑一个小规模真实批次。
3. 用真实新批次复查：生成入口、澄清、批次页、用例树、审查动作、资产落库、搜索、导出。
4. 找一个未参与开发的 QA 按任务脚本首次上手，记录卡点。
5. 没有 P0/P1 后，再准备 PR / 合并到 main。

## 最终判断

当前代码达到了“UI/UX 分支候选交付”的标准，足以让用户开始真实批次验证和首次上手验收。

它还没有达到“无需额外验证即可合入 main”的标准。剩余缺口集中在真实 LLM 跑批、破坏性 mutation 验收和真人首次使用验收，而不是当前 UI 静态/运行态阻断。
