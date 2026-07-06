# 测试资产模块树对齐实施清单

## File Scope

- 修改 `scripts/audit_export.py`
- 新增或修改 `tests/testcase_generator/test_audit_export_module_tree.py`
- 更新本任务文档

禁止改：

- DB/schema/API/UI
- `src/testcase_generator/stages/write_cases/convergence.py`
- `src/testcase_generator/stages/write_cases/node.py`
- verify 相关代码

## Steps

1. 提取纯函数：
   - `source_refs_of(record)`
   - `classify_case_for_audit(record)`
   - `build_audit_tree(cases)`
   - 写文件 helper 与 brief helper 分离

2. 实现业务模块分类：
   - source_refs / source_section 证据章节优先。
   - 关键词规则只在无稳定证据章节时兜底。
   - `§5.8` 内嵌资产区按真实业务模块归档，其余批创配置归 `批量创建广告`。
   - `§9`/`§10` 横切章节保留 `cross_cutting_tags`，但顶层尽量归真实业务模块。
   - branch_path 至少覆盖 `标题包` 的 `入口与页面预览`、`字数算法`、`自动拆包`、`联动分配`、`删除`。
   - branch_path 必须 canonicalize，不能把 PRD 标题碎片直接当目录名。
   - 无法归类进 `_review_required/unresolved_module`。

3. 改 `dump()` 输出：
   - `modules/` 写业务模块树。
   - `by_source_section/` 写旧平铺反查。
   - `index.json` 写 `audit_schema_version = 2`、业务模块清单、source-section 清单、unresolved 统计。

4. 加测试：
   - 多个标题包 source_section 聚合到一个 `标题包` 顶层模块。
   - `by_source_section` 仍能按原 source_section 反查。
   - unresolved 进入 review bucket。
   - `index.json` 同时包含业务模块和 source-section 索引。

5. 验证：
   - `uv run pytest tests/testcase_generator/test_audit_export_module_tree.py -q`
   - `uv run ruff check scripts/audit_export.py tests/testcase_generator/test_audit_export_module_tree.py`
   - 对已有 `.audit/0627...` 或小样本做输出结构抽查。

6. 新增校准包：
   - `--calibrate` 写入 `.audit/<batch>-module-tree-calibration/`，不覆盖 `.audit/<batch>/`。
   - 输出 `README.md`、`index.json`、`taxonomy_candidate.json`、`calibration_samples.jsonl`、`samples/*.md`。
   - 抽样策略：普通模块 10 条，大模块 20 条；按 branch 分层轮询，优先可疑 branch。
   - 可疑 branch 标记：`通用规则`、`unresolved`、纯序号、箭头/符号残留等。
   - 人工标注模板字段：`module_correct`、`corrected_module`、`branch_correct`、`corrected_branch_path`、`review_notes`。

## Self-Review Gate

实现后逐条反问：

- `modules/` 的顶层是否真是业务模块，而不是 source_section？
- `标题包` 是否从多个 PRD 小节收拢到一个目录？
- `source_section` 是否仍可反查？
- 是否有静默未分类？
- 是否误改了生成、verify、DB、API/UI？
- 校准包是否是独立目录，且不会破坏已有 findings 对旧审查包的引用？
- 抽样是否覆盖多个 branch，而不是只抽最大分支？

## 2026-07-03 增补：未分类 main 样本标题 fallback

背景：批次 `.audit/6f30e1bd-89ad-4e98-878c-4b48014eb1a4` 中 `_review_required/unresolved_module` 仍有 43 条非重复未分类，其中 4 条是 `bucket=main`。这些 case 的 `source_section=unresolved`，但标题里有明确业务实体，继续留在未分类队列会降低模块审查效率。

文件范围：

- 修改：`src/testcase_generator/services/module_tree_classifier.py`
- 修改：`tests/testcase_generator/test_audit_export_module_tree.py`
- 修改：`.audit/6f30e1bd-89ad-4e98-878c-4b48014eb1a4/REPORT.md`
- 修改：本任务 `design.md` / `implement.md`

实现清单：

- [x] `投放人` 作为窄口径 alias 归 `账户授权`，分支 `投放人管理`。
- [x] `媒体评估` / `media_evaluation_tags` / `素材` 归 `素材中心`，分支 `媒体评估与过滤`。
- [x] `任务状态` / `状态任务` / `操作列` 等归 `任务中心`，分支 `任务状态与操作`。
- [x] 不增加过宽 `任务` / `复用` 顶层 alias，避免批创“广告任务”等标题被误吸入任务中心。
- [x] 模块专属分支规则放在真实 `source_refs` heading 之后，避免覆盖有明确章节来源的分支。

离线复算结果：

- 非重复未分类：43 → 25
- `bucket=main` 未分类：4 → 0
- 4 条 main 样本归属：
  - `批量修改投放人按钮文案显示已选数量N` → `账户授权 / 投放人管理`
  - `媒体评估接口失败时素材的 media_evaluation_tags 保留上一次成功值` → `素材中心 / 媒体评估与过滤`
  - `不同任务状态下「复用」操作均常显可用` → `任务中心 / 任务状态与操作`
  - `「已取消」状态任务-操作列仅展示复用按钮` → `任务中心 / 任务状态与操作`

验证命令：

- [x] `uv run pytest tests/testcase_generator/test_audit_export_module_tree.py -q`
