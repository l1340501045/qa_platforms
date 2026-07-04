# UI/UX 分支真实批次与首次使用平台验收 Runbook

## 使用时机

周一回到公司网络、能访问 LLM 网关后执行。

目标不是跑最大 PRD 来证明一切，而是先用一个小规模真实批次证明当前 UI/UX 主链路没有断。完整大 PRD 批次可以随后作为生成质量回归，不应该和 UI 合并门槛混在一起。

## 0. 先确认代码状态

在仓库根目录先跑静态预检。如果 API / frontend / worker 还没启动，用这个命令即可：

```bash
uv run python scripts/ux_acceptance_preflight.py --skip-runtime
```

也可以手工核对：

```bash
git status --short --branch
git log --oneline -5
git diff checkpoint/architecture-migration-pre-ux...HEAD --name-only -- src/testcase_generator
```

期望：

- 当前分支是 `feat/qa-platform-ux-modernization`。
- 工作区干净。
- 最近提交包含 `补齐当前HEAD运行态验收` 和 `归档当前HEAD运行态验收任务`。
- 最后一条 diff 命令无输出，表示 UI/UX 分支没有动生成核心。

## 1. 启动环境

```bash
docker compose -f docker-compose.infra.yml up -d
uv run alembic upgrade head
./scripts/start_platform_services.sh
```

前端另开终端：

```bash
cd web
npm run dev -- --host 0.0.0.0 --port 3000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
curl -I http://127.0.0.1:3000
uv run celery -A src.platform_api.core.celery_app.celery_app inspect ping --timeout=5
```

服务启动后，推荐直接跑完整预检：

```bash
uv run python scripts/ux_acceptance_preflight.py
```

期望：

- API 返回 `{"status":"ok","version":"0.1.0"}`。
- 前端返回 `HTTP/1.1 200 OK`。
- worker 返回 `pong`。

## 2. 确认真实跑批配置

```bash
grep -E '^(LLM_PRIMARY_MODEL|LLM_VISION_MODEL|LLM_VERIFY_MODEL|LLM_CONCURRENCY)=' .env
rg "BEST_PRACTICE_GENERATION_CONFIG|cases_per_tp_cap|p0_quota_enabled" web/src/services/batchApi.ts src/platform_api/core/settings.py src/testcase_generator/pipeline/config.py
```

期望：

- `LLM_PRIMARY_MODEL=claude-opus-4-6`
- `LLM_VISION_MODEL=claude-opus-4-6`
- `LLM_VERIFY_MODEL=deepseek-v4-pro-office`
- `LLM_CONCURRENCY=8`
- 前端触发生成配置为 `existence_merge_enabled=true`、`split_cap_enabled=true`、`cases_per_tp_cap=4`、`p0_quota_enabled=false`。

## 3. 小规模真实批次验收

建议新建一个专门验收系统，避免污染现有业务系统：

```text
系统名称：ux_acceptance_YYYYMMDD
描述：UI/UX 合并前真实跑批验收
```

资料选择建议：

- 默认使用 [ux-small-batch-prd.md](./ux-small-batch-prd.md)。
- 这份样例覆盖权限、字段边界、CSV 上传、异步状态、失败重试、停止、筛选分页和导出，适合验证 UI/UX 主链路。
- 如果不用默认样例，也应选择一份 1-3 个模块的小 PRD 或从大 PRD 中复制一个闭环模块。
- 如果必须使用大 PRD，先接受耗时较长，不要把这一步当作 UI 分支最小合并门槛。
- 如果资料含图片，保留图片，验证视觉模型链路。

浏览器步骤：

1. 打开 `http://127.0.0.1:3000/`。
2. 不看说明，判断首页是否能让你进入“工作台”或“项目/系统”。
3. 进入“项目/系统”，创建验收系统。
4. 进入该系统知识库。
5. 上传前选择资料类型，例如 `PRD`。
6. 上传 [ux-small-batch-prd.md](./ux-small-batch-prd.md)，确认列表里的类型不是误落 `other`。
7. 点击“生成用例”，确认弹窗文案能让人理解这是一个真实生成任务。
8. 触发生成后记录跳转到的 `batch_id`。
9. 观察批次页：
   - 阶段进度是否变化。
   - 运行中/待澄清/失败/待审核状态是否可理解。
   - 如果待澄清，提交一条澄清后继续。
   - 如果失败，记录失败阶段和错误信息，不要重跑覆盖证据。
10. 批次到待审核后，检查用例树：
    - 模块不是 PRD 章节平铺。
    - 模块下允许出现分支树。
    - 左侧树不会默认展开到需要长时间滚动才能操作。
11. 抽查 5 条用例：
    - 标题是否像真实测试断言。
    - 步骤短但是否可执行。
    - 预期是否可观察。
    - 来源是否能追溯。
12. 进入“用例资产”，确认能按系统看到新批次资产。
13. 进入“全局搜索”，搜索一个新 PRD 中的关键词，确认能找到相关用例。
14. 进入“导出中心”，创建一次导出任务并确认能下载或看到完成状态。

记录：

- system id
- document id
- batch id
- 批次最终状态
- 总用例数
- 是否出现待澄清
- 是否出现失败
- 任何 UI 卡点截图或文字描述

## 4. 首次使用平台的 QA 演练

找一个具备 QA 背景但首次使用本平台的人。只给 TA 一个任务目标，不讲页面怎么用。

建议直接使用 [首次使用平台的 QA 演练观察表](./first-use-observation.md) 记录过程。

任务目标：

```text
请把这份 PRD 上传到平台，生成测试用例，找到需要审查的批次，抽查几条用例，然后导出结果。
```

观察规则：

- 不提前解释“知识库”“工作台”“用例资产”的含义。
- 不告诉 TA 应该点哪个按钮。
- TA 问“下一步在哪”时，先记录，再给最小提示。
- 不因为 TA 不懂平台术语就判失败；失败点是页面没有提供足够的下一步线索。

记录指标：

| 指标 | 通过口径 |
|---|---|
| 首次找到项目/系统 | 不超过 1 分钟 |
| 首次理解上传资料类型 | 不需要解释 `PRD/技术文档/测试规则` 的用途 |
| 上传后知道下一步生成 | 不需要从别的页面猜入口 |
| 生成后能回到工作台/批次页 | 不迷路 |
| 批次状态可理解 | 能说出“现在是生成中/待澄清/失败/待审核” |
| 审查页可操作 | 能找到模块树、用例列表、详情或操作 |
| 能找到导出 | 不需要口头告知入口 |

失败分类：

- P0：主流程无法继续。
- P1：没有解释就不知道下一步，或页面状态误导。
- P2：能完成但效率低、文案弱、布局拥挤。

## 5. 生成审查包

真实批次完成后，在仓库根目录执行：

```bash
uv run python scripts/audit_export.py <batch_id> --dump
```

期望出现：

```text
.audit/<batch_id>/
  index.json
  REPORT.md
  prd.md
  modules/
  image_captions.json  # 如有图片
```

把 `<batch_id>` 和 `.audit/<batch_id>/REPORT.md` 的前几段发给 Codex，我会继续按之前 `.audit` 多视图审查方式看用例质量。

## 6. 合 main 判定

可以进入 PR / 合 main 准备：

- 小规模真实批次能完成到待审核或归档。
- UI 没有 P0/P1 主流程卡点。
- 具备 QA 背景但首次使用本平台的人，能在少量提示内完成任务。
- 新批次能导出 `.audit` 审查包。
- 生成失败若发生，根因明确是 LLM 网关/模型/生成策略，而不是 UI/UX 主链路。

不能合 main：

- 上传、生成、批次页、审查、资产、搜索、导出任一主链路断。
- 系统列表统计再次显示假 0。
- 上传资料类型仍误落 `other`。
- 批次状态让首次使用平台的 QA 无法判断下一步。
- 用例树退回章节平铺，或默认展开到不可操作。

## 7. 完整大 PRD 批次

完整 PRD 大批次建议在小批次通过后再跑。它主要回答：

- 生成耗时和网关稳定性。
- 用例数量是否仍主观“灌水”。
- 模块树是否在大规模数据下仍合理。
- `.audit` 审查里 P0、needs_spec、to_fix、重复、待分类是否改善。

如果大批次失败，不自动阻塞 UI/UX 合并。先定位失败属于：

- UI/UX 主链路问题。
- LLM 网关或并发问题。
- testcase generator 质量策略问题。
- 具体 PRD 规模过大导致的运行成本问题。
