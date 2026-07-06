# 结构化覆盖（权限矩阵 + 状态转移）— 设计文档

> 状态：设计（brainstorming 产出，已与用户确认）。下一步：writing-plans 出实施计划（执行交 Claude Code，不走 gpt-review-gate）。
> 来源：批次 `0c9b63e6` 审查（`.audit/.../REPORT.md`，P0-3「权限矩阵/事件资产大面积漏测」、§5.9 状态机转移漏）+ findings/14 行业实践（ISTQB 状态转移/权限矩阵）。roadmap 用例质量侧落点 ⑫（结构化覆盖）第一批。
> 线 B（3 线分组 A/B/C 之一，价值最高、工作量最大）。范围本期只做**权限矩阵 + 状态转移**，决策表/RTM 二期。

## 1. 背景与目标

### 1.1 现状问题（审查实证）
- **权限矩阵零覆盖**：PRD §10.1 角色分类 / §10.2 数据权限定义了角色×资源权限，但用例几乎不覆盖（管理员/组长/投手最高危角色 untested）。
- **状态机转移漏测**：任务中心状态机（§5.9.3）等只测了部分正向转移，非法转移/终态后操作普遍缺失。
- **根因**：`rule-anchored` 每条规则只产 **1 个锚点**，无法把「角色×资源矩阵」「状态+转移」展开成组合覆盖；维度门控也不针对结构化组合。

### 1.2 目标
- 新增**结构化覆盖**：从 PRD 抽「权限矩阵」「状态机」结构定义 → **有界展开**成测试点 → 纳入覆盖闸保证不被 write_cases 漏。
- 架构**嵌入 test_points 阶段**（不改 LangGraph 拓扑，灰度直通，仿 rule_extract）。
- 灰度 `structural_coverage_enabled` 默认 False → **零回归**。

### 1.3 成功标准
- 对漫剧 PRD 能抽出权限矩阵（≥3 角色 × 若干资源）+ ≥1 个状态机（任务中心），展开出覆盖「每个 PRD 明确权限格子」「每个合法转移 + 关键非法转移」的测试点。
- 新批次 review 的 audit_report 显示结构化覆盖率；未覆盖项被 backfill 补齐。
- 开关关时流水线行为与现状逐条一致。

## 2. 范围
**做**：权限矩阵抽取器 + 状态机抽取器（LLM，结构化 schema）；有界展开器；`TestPointSchema` 加 `structural_type`/`structural_key`；test_points 末尾追加结构化点；覆盖闸纳入结构化覆盖 + backfill；灰度开关；单测 + 真实抽取验证。

**不做（YAGNI / 二期）**：决策表、RTM（二期）；全笛卡尔积权限 / 全 N-switch 状态机；不碰 verify/dedup/溯源；不改图拓扑。

## 3. 设计

### 3.1 结构化抽取器（嵌入 test_points，开关控制）
新增 `stages/test_points/structural/`：
- `schemas.py`：
  - `PermissionMatrix{roles: list[str], resources: list[str], grants: list[Grant]}`；`Grant{role, resource, operation, effect: Literal["allow","deny"], source_quote}`。
  - `StateMachine{name, states: list[str], transitions: list[Transition]}`；`Transition{src, dst, event, guard: str = "", source_quote}`。
- `permission_extractor.py` / `state_extractor.py`：`get_llm_client().generate_structured` 从 PRD（重点 §权限/状态机章节，输入用 parsed_context 章节文本）抽上述 schema。失败安全降级（返回空，不阻断）。

### 3.2 有界展开（`expander.py`）
- **权限**：对 `grants` 中 PRD 明确的格子各产 1 测试点（断言该 role 对 resource 的 operation = allow/deny）；再对每个 resource 补「有权角色×1 + 无权角色×1」等价类代表（去重）。**不全笛卡尔积**。
- **状态机**：每个 `transition` 产 1 测试点（0-switch，断言 src+event→dst）；+ 关键非法转移抽样（终态后再触发、PRD 未定义的跳转）。**不全 N-switch**。
- 产出 `TestPointSchema`，`structural_type ∈ {permission, state_machine}`，`structural_key` = 稳定标识（如 `perm:{role}:{resource}:{operation}` / `state:{machine}:{src}->{dst}`），`dimension` 取 `access_control`/`state_transition`，`priority` 走线 A 的 risk（或结构化默认：权限/非法转移=高）。

### 3.3 集成 test_points
- `TestPointSchema` 加 `structural_type: str | None = None`、`structural_key: str | None = None`（仿 `rule_id` 可选字段）。
- `test_points_node` 末尾（rule 锚点追加之后）：`if settings.structural_coverage_enabled:` 调抽取器+展开器，`test_points.extend(structural_points)` + 统一重编号。开关关时零影响。

### 3.4 覆盖闸（扩展 `rule_coverage_gate`）
- `review/node.py` 现有 `compute_rule_coverage`（规则锚点覆盖）旁，新增 `compute_structural_coverage(structural_points, covered_tp_ids)`：每个 `structural_key` 是否有用例覆盖；产出 `structural_coverage` 字段进 `AuditReport`（仿 `rule_cov_fields`）。
- 未覆盖的结构化点交 `backfill`（复用现有定向回填机制，backfill_node 识别 `structural_type`）。
- **与 rule 链解耦**：`structural_coverage_enabled` 独立控制结构化点的生成与 backfill，不依赖 `rule_coverage_gate_enabled`。开关开即全链路生效（抽取→展开→覆盖闸→定向回填）。

### 3.5 灰度与落库
- `settings.structural_coverage_enabled: bool = False`。
- `structural_type`/`structural_key` 经 test_point 落库（testcase.test_points 已有 derived_from JSONB；如需落库这两字段，确认 test_points 表是否有列——若无则只在运行期 state 用、不强落库，覆盖闸在内存判定即可，**不引入迁移**）。

## 4. 测试与验证
- 单测：抽取 schema 解析；有界展开数量（N 个 grant→N+等价类测试点；M 个 transition→M+关键非法）；`structural_key` 稳定唯一；`compute_structural_coverage` 命中/未命中；开关关零影响。
- 真实：对漫剧 PRD §10 + §5.9.3 跑抽取器（真实 LLM），人工核对权限矩阵/状态机抽得对不对、展开测试点是否覆盖关键格子/转移。

## 5. 风险与缓解
| 风险 | 缓解 |
|---|---|
| LLM 抽权限矩阵/状态机不准（漏角色/编转移） | 抽取带 `source_quote` 便于核对；有界展开只认 PRD 明确项；开关可关 |
| 组合仍偏多 | 有界展开（明确格子+等价类 / 0-switch+关键非法），不全展开 |
| `structural_type`/`structural_key` 落库需迁移 | 不落库专列，仅运行期 state + 覆盖闸内存判定（约束：无迁移） |
| 与 rule 链开关耦合 | 独立开关 `structural_coverage_enabled`，全链路（抽取→展开→覆盖闸→backfill）与 rule 链完全解耦 |

## 6. 文件改动清单（预估）
- **Create** `stages/test_points/structural/{__init__,schemas,permission_extractor,state_extractor,expander}.py`
- **Modify** `schemas/test_point.py`（+structural_type/structural_key）
- **Modify** `stages/test_points/node.py`（末尾追加结构化点，开关控制）
- **Modify** `stages/review/node.py`（+compute_structural_coverage 进 AuditReport）、`stages/review/backfill_node.py`（识别 structural 点回填）
- **Modify** `schemas/audit_report.py`（+structural_coverage 字段，默认值零回归）
- **Modify** `core/settings.py`（+structural_coverage_enabled）
- **Create** `tests/testcase_generator/test_structural_coverage.py`
