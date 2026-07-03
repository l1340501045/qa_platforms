# 测试资产模块树对齐

## Goal

把测试资产的主组织方式从“按 PRD `provenance.source_section` 平铺”调整为“按业务模块树组织”。`source_section` 继续保留为需求证据和追溯引用，但不再充当测试资产目录里的模块边界。

目标状态：

- 审查/导出的第一视图是产品业务模块，例如 `标题包`、`素材包`、`定向包`、`商品库`、`任务中心`。
- 业务模块内部允许出现分支树，例如 `标题包/新建编辑/字数算法`、`标题包/自动拆包`、`标题包/批创联动/标题分配`。
- 一个测试用例仍能追溯到一个或多个 PRD 小节，避免丢失来源证据。
- 执行视图、优先级视图、P0/冒烟/回归等不和业务模块树混在一起。

## Background

当前问题是“模块边界”和“需求出处”被混用了。

已确认的仓库事实：

- `scripts/audit_export.py` 当前按 `provenance.source_section` 分组落盘，`_module_of(c)` 直接返回 `source_section`，因此 `.audit/<batch>/modules/` 实际是 PRD 小节平铺。
- `.audit/0627.../index.json` 中已有大量类似 `5.6 标题包`、`5.6.0 入口与页面预览`、`5.6.1 字段与字数算法`、`5.6.2 自动拆包规则` 的平铺模块，导致同一业务模块被拆散。
- `src/platform_api/services/case_tree_service.py` 当前树形接口也是 `Document -> Module(source_section) -> Cases`。
- `tests/platform_api/test_case_tree_integration.py` 把 “source_section 正确分为模块” 写成了现有行为契约。
- `src/testcase_generator/schemas/test_case.py` 的 `Provenance` 只有 `source_section` 等来源字段，没有独立的 `business_module` / `branch_path` / `source_refs` 模型。
- `src/testcase_generator/stages/write_cases/provenance_tagger.py` 会从 `derived_from[0]` 推导 `source_section`，这适合做证据来源，不适合直接做测试资产模块树。

权威资料调研结论：

- Microsoft Azure Test Plans 将 test plan / test suite / test case 分成不同对象，静态 suite 更像资产组织文件夹，需求型 suite 用来关联 backlog requirement。也就是说，资产组织和需求追溯是两个轴。
- SmartBear Zephyr 支持 folders/subfolders 按功能、需求或测试类型组织测试资产，同时单独提供需求、用例、执行、缺陷之间的 traceability。
- SmartBear QMetry 使用 test case folder tree 组织测试用例，同时 Test Case、Test Cycle、Test Plan、Test Report 是不同区域，说明“资产库结构”和“执行计划/报告视图”应分离。
- ISO/IEC/IEEE 29119-4 和 NIST ACTS 强调测试设计技术、组合覆盖、边界值、等价类等覆盖模型。这些是 case 设计和覆盖维度，不应替代业务目录结构。

因此，本任务不应该把 PRD 小节名继续当成模块名，而应引入一个独立的测试资产模块树。`source_section` 是证据坐标，`business_module` / `branch_path` 才是资产组织坐标。

## Requirements

### R1. 分离业务组织和需求证据

每条测试用例需要同时支持：

- `business_module`：主业务模块名，例如 `标题包`。
- `branch_path`：模块内分支路径，例如 `["新建编辑", "字数算法"]` 或 `["自动拆包"]`。
- `source_refs`：一个或多个需求出处，兼容现有 `provenance.source_section`。

`provenance.source_section` 不删除，不改语义，只降级为证据引用字段。

### R2. 审查导出默认按业务模块树组织

`.audit/<batch>/modules/` 的默认主视图应从 source-section 平铺调整为业务模块树。

期望结构示例：

```text
.audit/<batch>/modules/
  01__标题包/
    module.json
    branches/
      01__新建编辑/
        01__字数算法/
          cases.jsonl
          brief.md
      02__自动拆包/
        cases.jsonl
        brief.md
      03__批创联动/
        01__标题分配/
          cases.jsonl
          brief.md
```

导出产物需要保留 source-section 视角，建议作为辅助索引：

```text
.audit/<batch>/by_source_section/
.audit/<batch>/index.json
```

### R3. 平台用例树应优先展示业务模块树

如果本任务覆盖平台 API/UI，则 case tree 的默认结构应从：

```text
Document -> source_section -> Cases
```

调整为：

```text
Document -> business_module -> branch_path -> Cases
```

source section 应显示为用例详情里的追溯信息，或作为筛选/反查视图，而不是主树节点。

### R4. 未能归类的内容进入显式审查桶

无法稳定映射到业务模块的用例，不应混入普通业务模块，也不应静默落到宽泛的 `未分类`。建议使用：

```text
_review_required/unresolved_module/
```

每条未归类用例需要给出原因，例如：

- source section 信息不足。
- 同时命中多个业务模块且置信度接近。
- PRD 小节名称是流程/规则，不是业务模块。

### R5. 兼容现有批次和旧消费者

初始对齐必须避免破坏历史批次读取：

- 旧批次只有 `source_section` 时，仍可展示为兼容视图。
- 新批次若已有 `business_module` / `branch_path`，优先使用新字段。
- `index.json` 应声明导出版本，例如 `audit_schema_version`。
- 如果保留旧目录结构，应明确标记为 `by_source_section`，避免继续误称为 modules。

### R6. 模块树映射需要可审查、可复用

模块树不应完全依赖一次性 LLM 判断。需要有可审查的映射来源，例如：

- PRD 章节到业务模块/分支的映射文件。
- 规则优先的启发式映射。
- LLM 仅作为建议或补全，输出置信度和理由。

映射文件示例：

```yaml
modules:
  标题包:
    aliases:
      - 标题包
      - 标题
    branches:
      新建编辑/字数算法:
        source_patterns:
          - 字段与字数算法
      自动拆包:
        source_patterns:
          - 自动拆包
      批创联动/标题分配:
        source_patterns:
          - 标题分配
```

### R7. 不把执行视图混进资产目录

P0、冒烟、回归、按风险、按维度、按负责人、按轮次等都属于执行/筛选视图。它们可以出现在 `views/` 或查询索引中，但不应成为业务模块树的一层。

### R8. 不改变本轮已完成的 cap/coverage 判定语义

本任务的核心是资产组织结构对齐，不应顺手修改现有 cap 策略、coverage atom 策略、existence merge 策略。除非后续实现时发现两者强耦合，否则只做读取、导出、展示层面的组织调整。

## Acceptance Criteria

- [ ] `.audit` 新批次主视图不再把 PRD 小节平铺称为模块。
- [ ] `标题包` 相关用例能聚合到一个业务模块目录下，并按 `字数算法`、`自动拆包`、`标题分配` 等分支组织。
- [ ] 每条新导出的 case 都能看到业务组织坐标和需求证据坐标：`business_module` / `branch_path` / `source_refs` 或等价结构。
- [ ] 旧的 `provenance.source_section` 仍可用于证据追溯和 source-section 反查。
- [ ] 未归类用例进入显式 review bucket，并带原因统计。
- [ ] `index.json` 能同时回答“有哪些业务模块”和“某个 PRD 小节贡献了哪些 case”。
- [ ] 现有旧批次读取不崩溃。
- [ ] 如覆盖平台 API/UI，`CaseTreeService` 的测试从 source-section grouping 改为 business-module tree grouping。
- [ ] 文档说明资产树、需求追溯、执行视图、覆盖维度四个轴的边界。

## Non-Goals

- 不在本任务内重新设计用例生成的全部 prompt。
- 不在本任务内重做 cap 数量策略。
- 不在本任务内把所有历史 `.audit` 批次强制迁移。
- 不把 `source_section` 删除或改成业务模块名。

## Recommended Rollout

建议分两阶段：

1. 先改 `.audit` 审查导出：新增业务模块树、source-section 辅助索引、unresolved review bucket，不动数据库结构。
2. 审查真实批次确认结构稳定后，再把 `business_module` / `branch_path` 持久化到 case schema、API、UI。

理由：当前最痛的是审查产物把模块平铺开，先在导出层修正可以最快验证“标题包这类复杂模块是否能自然收拢”。如果一开始就贯穿 DB/API/UI，改动面会覆盖 schema、生成、导出、平台服务、前端和测试，风险明显更高。

## Sequencing With Existing Quality Work

模块树对齐不是用例生成质量修复本身，而是审查和分析基础设施修复。它的优先级高于“继续人工审更多平铺模块”，但低于“已经明确会污染质量判断的核验/溯源硬缺陷”。

建议总顺序：

1. 冻结当前真实批次作为基线，不急着继续跑更多大批次。
2. 先把最新批次审查发现收敛成根因清单：区分系统 bug、PRD 自身矛盾、真实覆盖缺口、可接受噪声。
3. 先做低风险审查基础设施：`.audit` 业务模块树导出。它不改生成结果，只让后续审查更接近真实产品模块。
4. 再修会影响“我们到底该相信哪个 verdict”的问题：verify/grounding 落库、召回、概念混淆、同构判级一致性。
5. 再修生成侧覆盖和压缩问题：cap/coverage debt、存在性合并、P0 配额、占位分流、数值自校验。
6. 最后再考虑把业务模块树持久化进 case schema、API、UI。

这意味着：本任务的第一阶段应被当作“让审查更准、更省力”的前置工具，而不是替代之前的用例质量根因治理。
