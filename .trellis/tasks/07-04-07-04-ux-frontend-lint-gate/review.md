# 前端 ESLint 发布门禁补齐 Review

## 结论

本任务完成了阶段 E 报告中的 P1 发布门禁缺口：`npm run lint` 现在不再因为缺配置失败，而是能真实解析 Vite + React + TypeScript 源码并通过。

改动没有触碰后端生成逻辑，也没有改变 UI 的业务流程。业务代码改动只限于 lint 暴露出的低风险问题：删除过期 disable 注释、补齐 hooks 依赖、移除未使用 catch 变量。

## 关键决策自审

### 1. 为什么使用 `.eslintrc.cjs`

当前项目是 ESLint 8.x，`lint` 脚本仍使用 `eslint . --ext ts,tsx`。直接迁移 flat config 会扩大任务范围，还可能需要改脚本语义。因此采用 `.eslintrc.cjs`，兼容现有脚本和 `"type": "module"`。

这个选择偏保守，但更符合“补发布门禁，不重构工具链”的任务边界。

### 2. 为什么不直接 `plugin:react-hooks/recommended`

第一次接入 `plugin:react-hooks/recommended` 后，最新版插件引入了 React Compiler 相关规则，触发了大量 `set-state-in-effect`、`refs`、`preserve-manual-memoization` 问题。这些问题不适合在本任务中批量修，因为会把 lint 门禁收口变成 React 架构迁移。

最终只启用经典基线：

- `react-hooks/rules-of-hooks`
- `react-hooks/exhaustive-deps`

这能覆盖 hooks 调用顺序和依赖数组风险，同时不强迫当前代码一次性完成 React Compiler 适配。

### 3. 为什么关闭 `@typescript-eslint/no-explicit-any`

项目现有代码已经存在一些 API 错误对象和旧类型边界的 `any`。本任务目标是让 lint 成为可运行门禁，不是完成全项目类型收紧。保留该规则会把任务扩大成类型治理。

后续若要提高门禁强度，可以单独开任务逐步收紧，而不是在 UI/UX 发布收口里突然阻断。

### 4. 依赖风险

新增依赖均为 `devDependencies`，不会进入前端运行时 bundle。当前版本链路在本机 Node 25 下通过 `lint/typecheck/build/test:ui-models`。

`@typescript-eslint` 最新版要求 Node 18.18+。项目没有 `.nvmrc` 或 `engines` 约束，若后续要保证“别人 git 部署”完全一致，建议补一个 Node 版本约束文档或 `.nvmrc`。这不是本任务阻塞项，但属于发布工程化后续。

## 验证

| 命令 | 结果 |
|---|---:|
| `npm run lint` | 通过 |
| `npm run typecheck` | 通过 |
| `npm run build` | 通过，仍有既有大 chunk warning |
| `npm run test:ui-models` | 21 passed |
| `git diff --check` | 通过 |

## 剩余风险

- 目前 lint 是基础质量门禁，不是严格风格门禁。
- React Compiler 规则未启用；如果未来升级到 React Compiler，需要独立做 hooks/effect 架构梳理。
- 项目仍缺统一 Node 版本约束。
