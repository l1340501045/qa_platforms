"""批次用例全局横切分析（单模块审查 agent 看不到的跨模块视角）

读取 .audit/<batch>/modules/**/cases.jsonl，兼容旧版 .audit/<batch>/modules/*.cases.jsonl，聚合分析：
- conflict 用例全集（与 PRD 矛盾的明确错误）
- 维度命名规范（中英文混杂 / 语义重复）
- 用例结构完整度（步骤数 / 前置数 / 预期数分布）
- 近重复簇分布与样本
- 优先级与跨模块联动信号

用法：uv run python scripts/audit_global.py <batch_id>
输出：.audit/<batch_id>/findings/00_全局横切.md
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 已知语义重复的维度归并组（中英并存 → 同一测试意图）
DIM_SEMANTIC_GROUPS = {
    "正常流/正确性": [
        "functional_correctness",
        "正常流",
        "数据正确性",
        "functional_consistency",
        "functional_completeness",
    ],
    "边界值": ["boundary_value", "边界值", "text_length", "quantity_limit", "pagination_boundary", "data_range"],
    "异常/逆向/无效输入": ["invalid_input", "异常与逆向", "reversibility", "network_error", "timeout", "recovery"],
    "状态机": ["state_transition", "状态机"],
    "权限可见性": ["access_control", "permission_denied", "权限与可见性"],
    "并发一致性": ["concurrency", "并发与一致性", "idempotency"],
    "UI交互": ["ui_interaction", "UI交互", "sorting_filtering"],
    "接口契约": ["api_contract", "cross_system", "response_time", "default_values"],
}

# 跨模块联动关键词（标题命中“非自身模块”关键词 → 视为联动用例信号）
MODULE_KEYWORDS = {
    "账户授权": ["账户", "授权", "投放人", "解绑"],
    "漫剧库": ["漫剧库", "漫剧 id", "漫剧id", "聚合"],
    "投放链接": ["投放链接", "链接", "iap", "iaa", "监测"],
    "商品库": ["商品"],
    "素材中心": ["素材", "创意", "拒审", "低效"],
    "标题包": ["标题包", "标题库", "拆包", "通配符"],
    "定向包": ["定向"],
    "批创核心": ["批量创建", "批创", "出价", "预算", "提交"],
    "任务中心": ["任务中心", "任务列表", "重试", "回写"],
}


def _dim_values(dimensions) -> list[str]:
    out = []
    if isinstance(dimensions, list):
        for d in dimensions:
            if isinstance(d, str):
                out.append(d)
            elif isinstance(d, dict):
                out.append(str(d.get("name") or d.get("dimension") or d.get("type") or d))
    elif isinstance(dimensions, dict):
        out.extend(str(k) for k in dimensions.keys())
    return out


def _is_cn(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def _read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _load_cases(base: Path) -> list[dict]:
    """读取审查包中的用例，兼容新模块树与旧平铺 modules/*.cases.jsonl。"""
    files = sorted((base / "modules").glob("*/branches/**/cases.jsonl"))
    if not files:
        files = sorted((base / "modules").glob("*.cases.jsonl"))

    cases: list[dict] = []
    seen_ids: set[str] = set()
    for file in files:
        for case in _read_jsonl(file):
            case_id = str(case.get("id") or "")
            if case_id and case_id in seen_ids:
                continue
            if case_id:
                seen_ids.add(case_id)
            cases.append(case)
    return cases


def main() -> None:
    batch_id = sys.argv[1] if len(sys.argv) > 1 else "0c9b63e6-28cd-4efc-ae2e-0c9cbed9a9bb"
    base = ROOT / ".audit" / batch_id
    cases = _load_cases(base)

    n = len(cases)
    out = []
    out.append(f"# 全局横切分析（batch {batch_id}）\n")
    out.append(f"用例总数：**{n}**\n")
    if n == 0:
        out.append("未在审查包中读取到用例。请确认已先运行 `scripts/audit_export.py <batch_id> --dump`。")
        report = "\n".join(out)
        (base / "findings").mkdir(exist_ok=True)
        (base / "findings" / "00_全局横切.md").write_text(report, encoding="utf-8")
        print(f"未读取到用例，已写入 {base/'findings'/'00_全局横切.md'}")
        return

    # ── 全局分布 ──
    out.append("## 1. 全局分布\n")
    out.append(f"- verdict：{dict(Counter(c.get('verdict') for c in cases))}")
    out.append(f"- bucket：{dict(Counter(c.get('bucket') for c in cases))}")
    out.append(f"- priority：{dict(Counter(c.get('priority') for c in cases))}")
    p0 = sum(1 for c in cases if c.get("priority") == "P0")
    out.append(f"- **P0 占比：{p0/n*100:.1f}%**（P0 过高会稀释优先级信号，正常金字塔应 P0<30%）")
    out.append(f"- 近重复(is_duplicate)：{sum(1 for c in cases if c.get('is_duplicate'))}\n")

    # ── conflict 全集 ──
    conflicts = [c for c in cases if c.get("verdict") == "conflict"]
    out.append(f"## 2. conflict 用例全集（与 PRD 矛盾，{len(conflicts)} 条，必须修正）\n")
    for c in conflicts:
        v = c.get("verification") or {}
        out.append(f"### ◆ {c.get('title')}")
        out.append(
            f"- 所属：{(c.get('provenance') or {}).get('source_section')}　"
            f"priority={c.get('priority')}　dims={_dim_values(c.get('dimensions'))}"
        )
        if v.get("rationale"):
            out.append(f"- 判定理由：{v.get('rationale')}")
        if v.get("prd_evidence"):
            out.append(f"- PRD 依据：{v.get('prd_evidence')}")
        if v.get("unsupported_assertions"):
            out.append(f"- 不被支撑的断言：{v.get('unsupported_assertions')}")
        out.append("")

    # ── 维度命名规范 ──
    dim_counter = Counter()
    for c in cases:
        for d in _dim_values(c.get("dimensions")):
            dim_counter[d] += 1
    cn = {k: v for k, v in dim_counter.items() if _is_cn(k)}
    en = {k: v for k, v in dim_counter.items() if not _is_cn(k)}
    out.append("## 3. 维度命名规范（中英文混杂 / 语义重复）\n")
    out.append(f"- 不同维度标签总数：**{len(dim_counter)}**（中文 {len(cn)} 个 / 英文 {len(en)} 个）")
    out.append(f"- 中文标签使用量合计 {sum(cn.values())}；英文标签合计 {sum(en.values())} → **两套体系并存**")
    out.append("\n语义重复组（同一测试意图被拆成中英多个标签）：")
    for group, members in DIM_SEMANTIC_GROUPS.items():
        present = {m: dim_counter[m] for m in members if m in dim_counter}
        if len(present) > 1:
            out.append(f"- **{group}**：{present}")
    out.append("\n全部维度词频（降序）：")
    out.append(f"```\n{dict(dim_counter.most_common())}\n```\n")

    # ── 结构完整度 ──
    step_counts = [len(c.get("steps") or []) for c in cases]
    pre_counts = [len(c.get("preconditions") or []) for c in cases]
    exp_counts = [len(c.get("expected_results") or []) for c in cases]

    def _hist(vals):
        c = Counter()
        for v in vals:
            if v == 0:
                c["0"] += 1
            elif v == 1:
                c["1"] += 1
            elif v == 2:
                c["2"] += 1
            elif v <= 4:
                c["3-4"] += 1
            else:
                c["5+"] += 1
        return dict(c)

    out.append("## 4. 用例结构完整度（可执行性的客观侧面）\n")
    out.append(f"- 步骤数分布：{_hist(step_counts)}（均值 {sum(step_counts)/n:.1f}）")
    out.append(f"  - **仅 1 步的用例：{sum(1 for v in step_counts if v==1)} 条**（步骤过简，可能不可独立执行）")
    out.append(f"  - 0 步的用例：{sum(1 for v in step_counts if v==0)} 条")
    out.append(f"- 前置条件数分布：{_hist(pre_counts)}（均值 {sum(pre_counts)/n:.1f}）")
    out.append(f"  - **无前置条件的用例：{sum(1 for v in pre_counts if v==0)} 条**")
    out.append(f"- 预期结果数分布：{_hist(exp_counts)}（均值 {sum(exp_counts)/n:.1f}）")
    out.append(f"  - **无预期结果的用例：{sum(1 for v in exp_counts if v==0)} 条**\n")

    # 含糊词扫描
    vague_words = ["相关", "若干", "正确显示", "正常显示", "合理", "适当", "等等", "正确地", "应有"]
    vague_hits = []
    for c in cases:
        text = (c.get("title") or "") + " " + " ".join(
            (s.get("expected_result") or "") for s in (c.get("steps") or []) if isinstance(s, dict)
        ) + " " + " ".join(c.get("expected_results") or [])
        hit = [w for w in vague_words if w in text]
        if hit:
            vague_hits.append((c, hit))
    out.append(
        f"- **含糊表述命中**（预期/标题含「{','.join(vague_words)}」等无判定标准词）："
        f"{len(vague_hits)} 条（占 {len(vague_hits)/n*100:.1f}%）"
    )
    out.append("  样本：")
    for c, hit in vague_hits[:8]:
        out.append(f"  - [{hit}] {c.get('title')}")
    out.append("")

    # ── 重复簇 ──
    dups = [c for c in cases if c.get("is_duplicate")]
    dup_by_mod = Counter((c.get("provenance") or {}).get("source_section") for c in dups)
    out.append(f"## 5. 近重复簇（{len(dups)} 条标记为重复）\n")
    out.append("按模块分布（重复最多的模块）：")
    for mod, cnt in dup_by_mod.most_common(10):
        out.append(f"- {cnt}　{mod}")
    out.append("\n重复样本（标题）：")
    for c in dups[:10]:
        out.append(f"- {c.get('title')}")
    out.append("")

    # ── 跨模块联动信号 ──
    out.append("## 6. 跨模块联动信号（标题命中“他模块”关键词的用例数）\n")
    link_counter = Counter()
    for c in cases:
        title = (c.get("title") or "").lower()
        hit_mods = [m for m, kws in MODULE_KEYWORDS.items() if any(k in title for k in kws)]
        if len(hit_mods) >= 2:
            link_counter[" + ".join(sorted(hit_mods))] += 1
    out.append(f"- 标题同时命中 ≥2 个模块关键词的用例：**{sum(link_counter.values())}** 条（联动用例的粗略下界）")
    out.append("- Top 联动组合：")
    for combo, cnt in link_counter.most_common(15):
        out.append(f"  - {cnt}　{combo}")
    out.append("")

    # 端到端关键链覆盖探测
    e2e_signals = {
        "授权回收→提交部分失败": ["回收", "失效"],
        "提交→任务中心回写": ["任务中心"],
        "防超限/超限拦截": ["超限", "上限", "防超"],
        "事件资产检测/创建": ["事件资产", "资产"],
        "定时提交/调度": ["定时", "调度", "预约"],
    }
    out.append("- 端到端关键链覆盖探测（全量标题/步骤关键词命中数）：")
    for name, kws in e2e_signals.items():
        cnt = 0
        for c in cases:
            blob = (c.get("title") or "") + " ".join(
                (s.get("action") or "") + (s.get("expected_result") or "")
                for s in (c.get("steps") or []) if isinstance(s, dict)
            )
            if any(k in blob for k in kws):
                cnt += 1
        out.append(f"  - {name}: {cnt} 条")
    out.append("")

    report = "\n".join(out)
    (base / "findings").mkdir(exist_ok=True)
    (base / "findings" / "00_全局横切.md").write_text(report, encoding="utf-8")
    print(f"已写入 {base/'findings'/'00_全局横切.md'}（{len(report)} 字符）")
    # 控制台简报
    print(
        f"用例 {n} | conflict {len(conflicts)} | 仅1步 {sum(1 for v in step_counts if v == 1)} "
        f"| 含糊 {len(vague_hits)} | 维度标签 {len(dim_counter)}(中{len(cn)}/英{len(en)})"
    )


if __name__ == "__main__":
    main()
