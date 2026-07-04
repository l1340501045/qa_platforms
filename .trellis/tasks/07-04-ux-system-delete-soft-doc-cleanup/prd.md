# 系统删除忽略软删除文档

## 目标

修复文档软删除后系统仍无法删除的清理语义，避免项目/系统管理入口给出错误阻塞。

## 背景

阶段 E 文档类型上传探针发现：临时系统上传 PRD 后，调用文档删除接口会软删除文档；随后系统列表已不再显示该文档，但删除系统仍返回 409。用户视角是“系统已经没有可见文档，却仍删不掉”，会破坏项目/系统管理入口的可信度。

代码证据：

- `DocumentService.delete_document` 只设置 `Document.deleted_at`。
- `SystemService.delete_system` 直接删除 `public.systems`，依赖数据库外键报错兜底。
- `knowledge.documents.system_id` 对 `public.systems.id` 是 `ondelete=RESTRICT`，软删除 tombstone 仍会阻止物理删除系统。

## 需求

- 删除系统前应显式检查仍然有效的业务阻塞：
  - 未软删除文档存在时，仍拒绝删除系统。
  - 任何批次存在时，仍拒绝删除系统。
- 如果系统只剩软删除文档 tombstone，系统删除应成功，并清理这些 tombstone，避免外键残留。
- 不改变生成测试用例链路、批次链路、用例落库链路。
- 不做批次级级联删除，不让用户误删生成资产。

## 验收结果

- [x] 新增测试覆盖“系统仅剩软删除文档时可以删除，并清理 tombstone 文档”。
- [x] 新增测试覆盖“系统仍有有效文档时拒绝删除”。
- [x] 新增测试覆盖“系统仍有批次时拒绝删除”。
- [x] `uv run pytest tests/platform_api/test_system_service.py` 通过。
- [x] `uv run pytest tests/platform_api` 通过。
- [x] `uv run ruff check src/platform_api/services/system_service.py tests/platform_api/test_system_service.py` 通过。
- [x] `git diff --check` 通过。

## 不做

- 不改前端删除确认文案。
- 不迁移历史 `other` 文档类型。
- 不改变文档删除接口仍为软删除的行为。
