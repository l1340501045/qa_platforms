# 测试点元数据规范化（优先级 risk 模型 + 维度 enum 收敛）— 设计文档

> 状态：设计（brainstorming 产出，已与用户确认）。下一步：writing-plans 出实施计划（执行交 Claude Code，本流程不走 gpt-review-gate）。
> 来源：批次 `0c9b63e6` 用例质量审查（`.audit/.../REPORT.md`）+ 行业最佳实践对照（findings/14）；roadmap 用例质量侧落点 ⑩（优先级）+ ⑪（维度命名）。
> 这是「线 A」——3 线分组（A 元数据规范化 / B 结构化覆盖 / C 小补丁）中的第一条。

## 1. 背景与目标

### 1.1 现状问题（已核对代码）
1. **优先级 P0 泛滥 49.7%**：`test_points/node.py:126 _derive_priority` 按维度 `category` 硬映射（`functional`/`security`→P0），而绝大多数用例是 functional → P0 占比失真、无区分度。
2. **维度命名 98 个标签中英混杂**：`dimensions.yaml` 本是规范英文 enum（30+ `name`），但 ① `write_cases` prompt（node.py:100-108）用**中文维度名**引导（`正常流/边界值/异常与逆向…`），② 用例 `dimensions` 是 LLM 自由填（node.py:509 `dimensions=llm_case.dimensions`，无 enum 约束）→ 冒出 98 个混杂标签，破坏按维度统计/筛选/覆盖度量。

### 1.2 目标
- **①优先级**：引入 `risk = likelihood × impact`（各 1-3，LLM 给），代码算分映射 P0/P1/P2，取代维度硬映射，让分布天然合理（P0<30%）。
- **③维度**：用例 `dimensions` 强制收敛到 `dimensions.yaml` 的英文 enum（prompt 约束 + normalize 兜底）。
- **零回归**：仅改 test_points/write_cases 的元数据派生；不动覆盖逻辑/溯源/verify。

### 1.3 成功标准（用审查批次回归对比）
- 重新生成批次后 **P0 占比 < 30%**（当前 49.7%）。
- 用例 `dimensions` 标签种类从 ~98 收敛到 `dimensions.yaml` enum（~30）+ 极少量 `other`（告警可见）。
- risk 映射 / normalize 有单测；未命中 enum 的标签被日志暴露。

## 2. 范围
**做**：
1. `test_points` LLM schema 加 `likelihood`/`impact`/`risk_rationale`；prompt 改 risk 指引；新增 `risk_to_priority` 取代 `_derive_priority`。
2. `write_cases` prompt 维度清单对齐英文 enum + 给定 enum 约束；用例 `priority` 继承其 test_point；`dimensions` 经 `normalize_dimensions` 收敛。
3. 新增 `config/dimension_aliases.yaml`（同义词/中文/旧标签 → enum）。
4. 单测 + 回归对比脚本（复用审查批次）。

**不做（YAGNI）**：历史批次迁移（只管新生成）；维度中文展示（导出层，留后续）；接历史失败率动态优先级（无数据）；不改维度门控/覆盖裁剪/verify。

## 3. 设计

### 3.1 ①优先级 risk 模型
- `GeneratedTestPoint`（test_points/node.py:36）加：`likelihood: int`（1-3）、`impact: int`（1-3）、`risk_rationale: str = ""`。
- `TEST_POINTS_SYSTEM_PROMPT`（:54）把「priority 判定」段（:63-67）换成 risk 指引：
  - `impact`（业务伤害）：3=核心路径/资损/数据完整性/高频；2=一般功能；1=边缘/低频。
  - `likelihood`（易错程度）：3=边界/异常/复杂逻辑/并发/集成；2=一般分支；1=简单展示。
  - 要求给整数 1-3 + 一句 `risk_rationale`。
- 新增 `risk_to_priority(likelihood, impact) -> Literal["P0","P1","P2"]`：`risk=l*i`；`>=P0_MIN_RISK(默认6)→P0` / `>=P1_MIN_RISK(默认3)→P1` / `else P2`（阈值为模块常量，可调）。
- 落点 test_points/node.py:514-520：`priority = risk_to_priority(gtp.likelihood, gtp.impact)` 取代 `_PRIORITY_MAP.get(gtp.priority,...)`；删除/弃用 `_derive_priority`（:126，及 :462 `default_priority` 调用处一并改为 risk 或移除）。
- `write_cases` 用例 priority（node.py:508）：改为**继承其 test_point 的 priority**（按 `test_point_id` 查 `tp.priority`），不再用 `llm_case.priority`（保证用例与测试点优先级一致、单一事实源）。

### 3.2 ③维度 enum 收敛
- **唯一 enum = `dimensions.yaml` 的 `name` 集合**（运行时 `_load_dimensions()` 读取，已有此函数）。
- `WRITE_CASES_SYSTEM_PROMPT`（node.py:90，维度清单 :100-108）：把中文清单改为「英文 enum + 中文释义对照」，并明确要求 `dimensions` 字段**只能填 enum 的 `name`（英文）**。
- 新增 `config/dimension_aliases.yaml`：`{别名: enum_name}` 映射（基于审查 98 标签建：`正常流→functional_correctness`、`边界值→boundary_value`、`异常与逆向→invalid_input`、`状态机→state_transition`、`权限与可见性→access_control`、`并发与一致性→concurrency_state`… 右值均经自审核对在 `dimensions.yaml` 44 个真实 enum 内；无对应 enum 的别名[兼容性/需求待确认]不映射、走 `other` 告警）。
- 新增 `normalize_dimensions(dims: list[str]) -> list[str]`：逐个 `dim`：① 已是 enum→保留；② 命中 alias→映射；③ 未命中→`"other"` + `logger.warning`（暴露漏网，便于补表）。去重保序。
- 落点 write_cases/node.py:509：`dimensions=normalize_dimensions(llm_case.dimensions)`。

### 3.3 数据流 / 兼容
- test_points：LLM 给 likelihood/impact → 代码算 priority（likelihood/impact 仅生成期用，不新增 DB 列；`risk_rationale` 可丢或塞 `derived_from`，本计划丢弃）。
- write_cases：用例 priority 取自 test_point；dimensions normalize 后落库（JSONB，自动兼容）。
- 关时/旧批次：不受影响（旧批次不重算）。

## 4. 测试与验证
- 单测：`risk_to_priority`（边界 l*i ∈ {1,2,3,4,6,9} → P2/P2/P1/P1/P0/P0）；`normalize_dimensions`（enum 直通 / 中文映射 / 未命中→other+告警 / 去重）。
- 回归对比脚本 `scripts/metadata_regression.py`（轻量，离线读已有批次用例即可，不需 ParsedContext）：统计某批次的 `priority` 分布 + `dimensions` 标签种类数；改造后重新生成批次再统计，对比 P0 占比与标签收敛。

## 5. 风险与缓解
| 风险 | 缓解 |
|---|---|
| LLM 给 likelihood/impact 不稳/偏高 → P0 仍多 | 阈值常量可调（P0_MIN_RISK 调到 6 即需 l/i 双高）；回归脚本量化后再调 |
| alias 表覆盖不全 → 大量 other | 未命中告警暴露；首版表基于审查 98 标签建，跑一批后按 other 补全 |
| 用例 priority 继承 test_point 改动面 | 仅改 write_cases 构造一行；test_point 缺失时回退 P2 |

## 6. 文件改动清单
- **Modify** `src/testcase_generator/stages/test_points/node.py`（schema +risk 字段、prompt、`risk_to_priority`、落点替换 `_derive_priority`）
- **Modify** `src/testcase_generator/stages/write_cases/node.py`（prompt enum 对齐、priority 继承、dimensions normalize）
- **Create** `src/testcase_generator/config/dimension_aliases.yaml`
- **Create** `src/testcase_generator/stages/write_cases/dimension_normalizer.py`（`normalize_dimensions` + 加载 enum/alias）
- **Create** `tests/testcase_generator/test_priority_risk.py`、`tests/testcase_generator/test_dimension_normalize.py`
- **Create** `scripts/metadata_regression.py`
