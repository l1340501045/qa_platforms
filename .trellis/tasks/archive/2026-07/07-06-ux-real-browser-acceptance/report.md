# UI 真实浏览器验收报告

验收日期：2026-07-06
当前分支：`feat/qa-platform-ux-modernization`
最新批次：`5ad9f447-4502-447e-8c8a-cd818e370248`

## 结论

本轮判定：**FIX THEN GO**。

解释：真实浏览器巡检中发现一个 1024 宽 P1 问题：批次审查页行内操作中的“删除”按钮被表格横向滚动挤出视口。已在本轮修复并复测通过。修复后，API / worker / 前端在线，5 个目标路由可访问，桌面 1440 与 1024 宽核心页面无页面级横向溢出，批次页关键审核动作在 1024 宽全部可见。

父任务仍不能整体标记完成：还缺一个具备 QA 背景但首次使用本平台的真人演练；另外生成侧 `needs_spec/to_fix` 质量债务需要拆出独立任务处理，不应算 UI/UX 已完全收口。

## 环境证据

预检命令：

```bash
./.venv/bin/python scripts/ux_acceptance_preflight.py --allow-dirty
```

结果摘要：

- 当前分支：PASS，`feat/qa-platform-ux-modernization`
- 工作区：PASS，存在导出相关脏改动但通过 `--allow-dirty` 放行
- 生成核心 diff：PASS，`src/testcase_generator` 无变更
- 验收资料：PASS
- `.env` 模型配置：PASS
- 生成配置：PASS，`existence_merge_enabled=True`、`split_cap_enabled=True`、`cases_per_tp_cap=4`、`p0_quota_enabled=False`
- API：PASS，`{"status":"ok","version":"0.1.0"}`
- Frontend：PASS，HTTP 200
- Worker：PASS，`celery@LaceyMac: OK`

服务启动方式：

```bash
./scripts/start_platform_services.sh
cd web && npm run dev -- --host 0.0.0.0 --port 3000
```

## 路由验收

| 路由 | 结果 | 观察 |
|---|---|---|
| `/review` | PASS | 工作台能明确展示待澄清/失败/待审核/生成中队列，推荐处理顺序可见，待审核批次入口清楚。 |
| `/batches/5ad9...` | PASS after fix | 批次状态、阶段进度、待审/需修改/待澄清指标、模块树、审查动作完整可见；1024 宽操作列已修复。 |
| `/case-library` | PASS | 主集候选、全部资产、待处理资产三态明确；默认主集候选明确提示仍需结合审查状态，不误称为已确认资产。 |
| `/systems/6b0.../documents` | PASS | 上传前资料类型可见，默认 PRD 类型清楚，三步主流程“上传资料 -> 生成批次 -> 进入审查”明确。 |
| `/exports` | PASS | 导出中心说明 Markdown/Excel 使用场景，下载入口跟随任务主列，失败恢复提示清楚。 |

证据文件：

- `evidence/review-1440.png`
- `evidence/batch-1440.png`
- `evidence/batch-1024-after-column-fit.png`
- `evidence/case-library-1440.png`
- `evidence/case-library-1024-pending.png`
- `evidence/documents-1440.png`
- `evidence/exports-1024.png`
- `evidence/sweep-1440.json`
- `evidence/responsive-interactions.json`

## 发现与修复

### Finding 1 [P1] 1024 宽批次审查页“删除”动作不可见

修复前证据：

- 1024 宽下，首行按钮右边界：
  - `确认.right = 922.95`
  - `需修改.right = 988.95`
  - `删除.right = 1040.95`
- 视口宽度为 `1024`，所以“删除”落到可视区外。
- 这违反 `.trellis/spec/frontend/case-asset-browser-pattern.md` 的要求：工作台审核动作 `确认 / 需修改 / 删除` 必须在 1024 宽度下可见，不能长期放在横向滚动不可见区域。

根因：

- `CaseAssetTable` 在带 `renderActions` 时仍使用偏宽的标题列和固定 `scroll.x=760`。
- 批次页的右侧工作区在 1024 宽下只有约 `694px`，表格实际需要横向滚动。
- 操作列不是固定右列，三个文字按钮加间距后超过可见区域。

修复：

- `CaseAssetTable` 对“带操作列”的表格使用更紧凑的列宽：标题列换行，优先级/质量/可信度/状态列收窄。
- 操作列默认宽度从 `160` 调整为 `132`，并 `fixed: 'right'`。
- 批次页审核按钮间距改为 `Space size={0}`，按钮 `paddingInline=4`。

修复后证据：

- 1024 宽下，首行按钮右边界：
  - `确认.right = 896.58`
  - `需修改.right = 948.58`
  - `删除.right = 986.58`
- `删除.right < 1024`，三枚操作全部可见。
- 页面级 `bodyScrollWidth = 1024`，无页面级横向溢出。
- 表格头部 `标题 / 优先级 / 质量 / 可信度 / 状态 / 操作` 均在 `x=289` 到 `x=983` 范围内。

## 质量债务边界

本轮只处理 UI/UX 可操作性问题，没有改变后端生成逻辑，也没有修改 `src/testcase_generator/**`。

上一轮真实批次审查发现的生成侧问题仍然存在，包括：

- `needs_spec=632`
- `to_fix=59`
- 未归入模块树 `_review_required/unresolved_module=44`

这些不应由 UI 浏览器验收任务吞掉。UI 当前已经能表达“主集候选 / 待处理资产 / 待澄清 / 需修复”，但生成侧仍要单独处理“待确认问题不应伪装成可执行用例”“枚举/接口字段必须原文锁定”等策略问题。

## 验证命令

```bash
npm run test:case-assets
npm run build
```

结果：

- `test:case-assets`：5 passed
- `npm run build`：通过；仅保留 Vite chunk size warning，非本次改动阻塞

## 自审

- 本报告的 UI 结论来自真实浏览器 Playwright 巡检，不是只看代码或数据库。
- 本轮没有触发上传、生成、审查状态修改或导出任务创建；所有页面访问和切换都是只读。
- 本轮发现的 P1 已直接修复并用同一脚本复测，避免把已知 UI 问题留给后续批次。
- 1024 宽复测覆盖了批次页目录收起、批次页操作列、用例资产待处理资产切换、导出中心。
- 未完成项是父目标级别的真人首次使用演练，不是本任务浏览器自动巡检能替代的证据。
