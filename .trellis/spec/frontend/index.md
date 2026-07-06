# 前端开发规范

> 仓库前端真实模式索引。技术栈：React 18 + Ant Design 5 + Zustand + axios + Vite。
> 原则：只记录代码里**真实存在**的写法，每条带 `文件:行号` 锚点。

---

## 规范索引

| 文件 | 内容 | 状态 |
|------|------|------|
| [表单模式](./form-pattern.md) | 增/改/删表单、校验、反馈、四层数据流、axios 信封解包 | ✅ 已填（code-backed） |
| [用例资产浏览模式](./case-asset-browser-pattern.md) | 用例树归一化、递归 branch_path、共享树/表格组件、工作台审核动作插槽 | ✅ 已填（code-backed） |
| [页面骨架与信息架构模式](./layout-shell-pattern.md) | 工作流导航、PageShell/PageHeader/FilterBar/MetricStrip/SplitPane/EmptyState 接入约定 | ✅ 已填（code-backed） |

---

## 待补（按需，非本次 bootstrap 范围）

- 列表/分页页模式
- Zustand store 组织约定（`stores/*.ts`）
- 类型定义约定（`types/index.ts`）
