# 全局布局窄屏导航可用性 Implement

## Checklist

1. 修改 `web/src/layouts/MainLayout.tsx`
   - 引入 `Button`、`Drawer`、`Grid`、`MenuOutlined`。
   - 抽出统一菜单点击函数。
   - 桌面保留 `Sider`。
   - 窄屏 Header 显示菜单按钮，Drawer 内复用菜单项。
   - 保持现有 selectedKey 判断。

2. 验证
   - `cd web && npm run lint`
   - `cd web && npm run test:ui-models`
   - `cd web && npm run build`
   - `git diff --check`

3. Review
   - 自审桌面行为是否被误改。
   - 自审窄屏是否没有固定侧栏占宽。
   - 自审没有碰后端/生成链路。

## Validation Notes

当前本机 API/前端服务未启动，无法直接浏览器截图验收；本任务优先用静态构建和类型检查保证实现正确。若后续服务启动，可在 375、768、1024、1440 宽度下补浏览器验收。
