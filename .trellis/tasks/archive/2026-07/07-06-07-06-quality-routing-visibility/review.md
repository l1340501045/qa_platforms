# 质量分流可见性实现复审

日期：2026-07-06
分支：`feat/qa-platform-ux-modernization`

## 改动范围

- `web/src/components/case-assets/caseDisplay.tsx`
  - 将质量桶、核验结论、审查诊断的展示元数据集中到共享常量。
  - 表格质量标签不再直出 `grounded/ungrounded/undefined/conflict` 英文枚举。
- `web/src/pages/Workbench/index.tsx`
  - 在批次页阶段进度后新增“质量分流”摘要。
  - 提供“只看主集 / 处理待澄清 / 查看待修正 / 查看冲突”快捷筛选。
  - 筛选项复用共享中文业务文案，内部枚举值不变。
- `web/src/pages/CaseLibrary/index.tsx`
  - 用例资产页复用同一套质量筛选中文文案。

## 自审结论

- 没有改后端 API、数据库、worker、生成 pipeline 或导出任务语义。
- 没有触碰当前保留中的导出中心脏改动。
- 质量分流条只解释和驱动已有筛选，不阻塞“确认 / 需修改 / 删除 / 触发迭代 / 落库归档”主流程。
- 计数来自当前 `CaseTreeReview` 用例树；当用户已设置质量筛选时，页面明确提示“当前计数受质量筛选影响”。
- UI 继续使用现有 Ant Design 后台风格，没有引入 landing、装饰背景或新视觉体系。

## 验证

```bash
cd web
npm run test:case-assets
npm run build
npm run lint
```

结果：

- `test:case-assets`：5 passed
- `build`：通过；仅保留 Vite 既有 large chunk warning
- `lint`：通过

## 残留风险

- 本次没有启动真实前后端做浏览器截图验收；已通过 TypeScript、Vite build、lint 和资产模型测试保证编译与共享模型安全。
- 质量分流统计当前按“当前用例树/筛选结果”展示，不额外请求全量批次统计；这避免新增接口，但筛选后计数会跟随收窄。
