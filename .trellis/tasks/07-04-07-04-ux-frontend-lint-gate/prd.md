# 前端 ESLint 发布门禁补齐

## 目标

补齐前端 ESLint 配置和必要脚本依赖，让 UI/UX 分支发布前质量门禁可运行，支撑“其他人 git 部署后也能执行基础质量检查”的交付目标。

## 背景

阶段 E 运行态验收中，`npm run lint` 失败，原因不是业务代码错误，而是 ESLint 找不到配置文件。当前 `web/package.json` 已有 `lint` 脚本，但缺少 TypeScript/React 项目所需的 ESLint 配置和依赖。

## 约束

- 不改动后端生成逻辑。
- 不重构 UI 业务行为。
- 不把 lint 规则配置得过重，避免一次性引爆大量历史风格问题。
- 新增依赖必须进入 `web/package-lock.json`，保证别人安装后可复现。
- `npm run lint` 要覆盖 `ts/tsx` 源码，并能解析当前 Vite + React + TypeScript 项目。

## 验收结果

- [x] `npm run lint` 成功执行并通过。
- [x] `npm run typecheck` 通过。
- [x] `npm run build` 通过。
- [x] `npm run test:ui-models` 通过。
- [x] `git diff --check` 通过。
- [x] 只提交前端 lint 门禁和 Trellis 任务相关文件，不混入后端生成逻辑改动。

## 不做

- 不引入格式化器迁移。
- 不把 ESLint 升级到全新 major 或做大规模依赖升级。
- 不通过关闭 `lint` 脚本、降低脚本覆盖面、或把源码目录排除来伪造通过。
