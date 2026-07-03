# 测试资产模块树对齐设计

## Scope

本阶段只改 `.audit` 审查导出层。输入仍是数据库里的 `TestCase.provenance.source_section` 与用例字段；输出新增业务模块树视图和 source-section 反查视图。

不改：

- `GeneratedTestCase` / DB schema / alembic
- `CaseTreeService` / API / UI
- 生成、verify、convergence/cap 语义

## Data Flow

```text
TestCase.provenance.source_section
  -> source refs extraction
  -> deterministic module classification
  -> business module tree files
  -> by_source_section files
  -> index.json dual index
```

## Classification Contract

导出阶段为每条 case 派生审查坐标：

- `business_module`: 主业务模块，例如 `标题包`。
- `branch_path`: 模块内分支路径，例如 `["自动拆包"]`、`["新建编辑", "字数算法"]`。
- `source_refs`: 需求证据来源，来自 `provenance.derived_from` 和 `provenance.source_section` 去重合并。
- `classification_reason`: 命中的规则说明。
- `classification_confidence`: `rule` 或 `unresolved`。

当前采用确定性规则，不调用 LLM。规则来源优先级：

1. 需求证据章节优先。`source_refs` 是事实锚点，先按 `§5.x` / `§7` / `§8` / `§9` / `§10` 等章节映射业务模块。
2. `§5.8` 的内嵌资产区按业务归属映射：漫剧选择归 `漫剧库`，头条账户归 `账户授权`，创意素材归 `素材中心`，标题包归 `标题包`，商品选择归 `商品库`；其余批创配置仍归 `批量创建广告`。
3. `§9 字段约束`、`§10 权限说明` 作为横切维度保留 `cross_cutting_tags`，但顶层仍尽量归到真实业务模块，例如 `账户授权/字段约束`、`任务中心/权限`。
4. 无稳定证据章节时，才使用明确业务关键词 alias 兜底。
5. 无法归类则进入 `_review_required/unresolved_module`。

2026-07-03 增补：`source_section=unresolved` 不代表一定无法归类。若标题中存在窄口径业务实体，可进入对应业务模块，同时仍保留原 `source_refs=["unresolved"]` 作为证据问题：

- `投放人` → `账户授权 / 投放人管理`
- `媒体评估`、`media_evaluation_tags` → `素材中心 / 媒体评估与过滤`
- `任务状态`、`状态任务`、`操作列`、`已取消`、`复用` → `任务中心 / 任务状态与操作`

该 fallback 只用于业务模块树组织，不改变 `bucket` / `verdict`；需求待确认、技术派生或无证据问题仍通过 verify/audit 口径暴露。

## Output Structure

```text
.audit/<batch>/
  modules/
    01__标题包/
      module.json
      branches/
        新建编辑/
          字数算法/
            cases.jsonl
            brief.md
        自动拆包/
          cases.jsonl
          brief.md
  by_source_section/
    01__prd_xxx_5_6_1_字段与字数算法.cases.jsonl
    01__prd_xxx_5_6_1_字段与字数算法.brief.md
  _review_required/
    unresolved_module/
      cases.jsonl
      brief.md
  index.json
```

## Compatibility

- `modules/` 变为业务模块树主视图。
- 旧的 source-section 平铺能力保留在 `by_source_section/`，并按全部
  `source_refs` 建反查索引；多来源用例会出现在每个相关证据坐标下。
- `index.json` 增加 `audit_schema_version = 2`，同时包含 `modules` 和 `source_sections`。
- case JSON 中不改原 `provenance`，只在导出 dict 里附加 `audit_classification`。

## Calibration Review Package

模块树在产品化前必须先作为候选 taxonomy 被校准。校准包是独立输出，
不覆盖正式 `.audit/<batch>/`，避免断开已有 findings 中的旧路径引用。

```text
.audit/<batch>-module-tree-calibration/
  README.md
  index.json
  taxonomy_candidate.json
  calibration_samples.jsonl
  prd.md
  image_captions.json
  samples/
    01__标题包.md
    02__批量创建广告.md
    ...
```

校准包内容：

- 按模块分层抽样：普通模块 10 条，大模块 20 条。
- 分支内分层抽样：优先覆盖不同 branch，且优先暴露可疑 branch。
- 每条样本带人工标注空位：顶层模块是否正确、branch 是否正确、纠正值、备注。
- `taxonomy_candidate.json` 汇总当前规则候选、观测到的 branch、样例、质量标记。
- `index.json` 声明验收门槛：顶层模块准确率目标 95%，branch 准确率目标 85%，脏 branch 名目标 0。
- 分支名必须 canonicalize，不能把 `1）`、`/ 拒审过滤`、`→ 事件资产映射表`、`/ 广告名称 / 任务名称）` 等 PRD 标题残片当成稳定 branch。

校准通过前不做：

- 不把 `business_module` / `branch_path` 写入 DB。
- 不接 API/UI。
- 不把当前规则视为最终业务 taxonomy。

## Critical Risks

- 不能把 PRD 小节名改个目录名后继续平铺。必须让 `标题包` 相关小节聚合到同一个顶层业务模块。
- 不能丢掉 PRD 原文审查基准。业务分支 brief 需要汇总相关 source sections，并包含可匹配到的 PRD 原文块。
- 规则分类可能不完美，必须显式输出 unresolved review bucket，而不是静默归入普通模块。
- 校准包不能覆盖正式审查包；否则已有多智能体审查 findings 的旧路径会断。
