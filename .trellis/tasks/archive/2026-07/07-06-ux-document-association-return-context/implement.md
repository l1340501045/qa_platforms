# 文档详情关联跳转保留追溯上下文 Implement

## Checklist

1. 在 `web/src/utils/batchReturn.ts` 增加 `buildAssociatedDocumentUrl`。
2. 在 `web/src/utils/batchReturn.test.ts` 增加测试：
   - 普通文档详情 -> 关联文档。
   - 知识库来源 -> 关联文档保留 `document_from=knowledge`。
   - 搜索来源 -> 关联文档保留搜索上下文。
3. 修改 `web/src/pages/DocumentDetail/index.tsx`：
   - 识别 `from=document`。
   - 返回入口文案显示 `返回来源文档`。
   - 关联文档链接使用 `buildAssociatedDocumentUrl`。
4. 验证：
   - `cd web && npm run test:ui-models`
   - `cd web && npm run lint`
   - `cd web && npm run build`
   - `git diff --check`

## 回滚

回滚本次提交即可恢复裸关联文档跳转；没有后端迁移或数据变更。
