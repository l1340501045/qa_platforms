# 批次页质量分流总览稳定化实施计划

## 实施清单

- [x] 在 `Workbench/index.tsx` 中增加全批质量快照状态：
  - loading
  - error
  - cases
- [x] 使用现有 `getCaseTree(batch.system_id, { batch_id })` 拉取无质量筛选的全批树。
- [x] 复用 `normalizeCaseTreeDocuments` / `getCasesForNode` 并新增 `workbenchQuality` 纯函数，把全批树转成统计。
- [x] 保留 `allCasesForIterate` 作为当前队列数据源，不把它改成全批数据，避免影响“触发迭代”行为。
- [x] 调整质量分流区文案：
  - 明确“全批质量总览，不随下方筛选变化”。
  - 当筛选存在时显示当前队列摘要。
  - 总览加载失败显示 warning，不显示假 0。
- [x] 如抽出统计/筛选摘要纯函数，补充 node test。
- [x] 跑前端相关验证。

## 预计改动文件

- `web/src/pages/Workbench/index.tsx`
- 可能新增 `web/src/utils/workbenchQuality.ts`
- 可能新增 `web/src/utils/workbenchQuality.test.ts`
- 本任务 Trellis 文档

## 验证命令

```bash
cd web
npm run test:ui-models
npm run build
```

如果只改页面 JSX 且未新增纯函数测试，仍至少跑：

```bash
cd web
npm run build
```

## 回滚点

- 本切片应是前端展示改动。若出现接口压力或页面渲染问题，可以回滚新增的全批快照请求和质量分流区 UI，不影响生成主流程。
- 不触碰后端 pipeline，因此无需数据迁移或 worker 回滚。

## 批判性 Review

计划有两个容易跑偏的点：

1. 不要顺手修生成质量问题。真实跑批报告里的 typed numeric、P0 过宽、模块归类残留很重要，但不属于这个 UI 切片。
2. 不要让全批快照污染迭代逻辑。`triggerIterate` 必须继续基于当前队列里的 `needs_modification`，否则用户在筛选某个模块时可能误触发全批需修改用例迭代。

只要实现保持这两个边界，本切片可以独立验证、独立回滚，并且能明显改善 QA 首次进入批次页时的决策动线。
