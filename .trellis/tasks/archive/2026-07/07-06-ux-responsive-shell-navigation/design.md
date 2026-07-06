# 全局布局窄屏导航可用性 Design

## 当前结构

- `web/src/App.tsx` 负责路由。
- `web/src/layouts/MainLayout.tsx` 负责全局 `Sider + Header + Content`。
- `menuItems`、`selectedKey` 和 `currentItem` 都在 `MainLayout` 内部。

## 设计

使用 Ant Design 现有组件完成自适应壳层：

- 通过 `Grid.useBreakpoint()` 判断当前是否为桌面布局。
- `md` 及以上继续渲染 `Sider`，宽度沿用 `layoutTokens.sidebarWidth`。
- 小于 `md` 时不渲染固定 `Sider`，在 `Header` 左侧显示 `MenuOutlined` 按钮。
- 点击菜单按钮打开 `Drawer`，抽屉内复用同一份 `Menu` 配置。
- 菜单点击统一走 `handleMenuClick(key)`；窄屏抽屉点击后关闭抽屉，桌面不受影响。

## 兼容性

- 不改 `App.tsx` 路由，不改默认首页跳转。
- 不改业务页面 `PageShell` / `SplitPane` / 表格内部逻辑。
- 不改通知组件，只调整 Header 容器布局以避免窄屏重叠。

## 回滚

如果窄屏抽屉引入问题，可回滚 `web/src/layouts/MainLayout.tsx` 的本次提交；后端和生成链路没有迁移或数据变更。

## 设计自审

- 为什么不用底部导航：这是桌面优先的企业 QA 工作台，底部导航会在数据表格场景占用纵向空间，并引入第二套导航模式。
- 为什么不改首页默认到项目/系统：当前前端规范已明确 `/` 默认进入工作台；这是更大的产品决策，不在本任务中偷偷改变。
- 为什么不用 CSS media query 单独隐藏：导航状态、高亮、点击关闭抽屉都需要 React 状态，使用 `Grid.useBreakpoint()` 和 Ant Drawer 更贴近现有栈。
