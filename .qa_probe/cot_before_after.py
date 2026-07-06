"""落点⑥ CoT 溯源接地 before/after 对照验证

用法: uv run python .qa_probe/cot_before_after.py

需要 LLM_API_KEY + DATABASE_URL 环境变量。缺失时跳过并提示。
对一份真实 doc，在 grounded_provenance_enabled 关/开各跑一次生成，
落盘两份用例，调度量尺子打印对照：引用精确率、对齐分布、有据断言绑定率。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "eval", "provenance"))


def _check_env():
    missing = []
    if not os.environ.get("LLM_API_KEY"):
        missing.append("LLM_API_KEY")
    if not os.environ.get("DATABASE_URL"):
        missing.append("DATABASE_URL")
    if missing:
        print(f"[SKIP] 缺少环境变量: {', '.join(missing)}。需要真实 LLM + DB 才能跑 before/after。")
        print("       设置后重跑: uv run python .qa_probe/cot_before_after.py")
        sys.exit(0)


def main():
    _check_env()

    import json

    from metrics import alignment_distribution, citation_precision, grounded_assertion_rate

    print("=" * 60)
    print("落点⑥ CoT 溯源接地 before/after 对照")
    print("=" * 60)
    print()
    print("此脚本需在真实流水线环境运行（LLM_API_KEY + DATABASE_URL）。")
    print("执行步骤：")
    print("  1. grounded_provenance_enabled=false 跑 write_cases → baseline 用例")
    print("  2. grounded_provenance_enabled=true  跑 write_cases → grounded 用例")
    print("  3. 对比度量：citation_precision / alignment_distribution / grounded_assertion_rate")
    print()
    print("手动验证要点：")
    print("  - 开后 引用精确率↑、unresolved↓")
    print("  - 抽查 verbatim_excerpt 确是支撑该断言的原句（非前200字）")
    print("  - 无推理过程泄漏进 JSON 字段")
    print()

    # 如果存在落盘的对照结果，加载并计算度量
    baseline_path = ".qa_probe/baseline_cases.json"
    grounded_path = ".qa_probe/grounded_cases.json"

    if os.path.exists(baseline_path) and os.path.exists(grounded_path):
        print("[加载已有对照数据]")

        class _Prov:
            def __init__(self, g):
                self.grounding = g

        class _Case:
            def __init__(self, p):
                self.provenance = _Prov(p)

        with open(baseline_path) as f:
            baseline_raw = json.load(f)
        with open(grounded_path) as f:
            grounded_raw = json.load(f)

        def _to_cases(raw):
            cases = []
            for c in raw:
                g = c.get("provenance", {}).get("grounding")
                if g:
                    cases.append(_Case(g))
            return cases

        b_cases = _to_cases(baseline_raw)
        g_cases = _to_cases(grounded_raw)

        print(f"\n{'指标':<30} {'baseline':>10} {'grounded':>10} {'delta':>10}")
        print("-" * 62)

        bp = citation_precision(b_cases) if b_cases else 0.0
        gp = citation_precision(g_cases) if g_cases else 0.0
        print(f"{'citation_precision':<30} {bp:>10.3f} {gp:>10.3f} {gp - bp:>+10.3f}")

        br = grounded_assertion_rate(b_cases) if b_cases else 0.0
        gr = grounded_assertion_rate(g_cases) if g_cases else 0.0
        print(f"{'grounded_assertion_rate':<30} {br:>10.3f} {gr:>10.3f} {gr - br:>+10.3f}")

        bd = alignment_distribution(b_cases) if b_cases else {}
        gd = alignment_distribution(g_cases) if g_cases else {}
        print(f"\n{'对齐分布':<20} {'baseline':>12} {'grounded':>12}")
        print("-" * 46)
        for k in ["verified", "fuzzy", "relocated", "unresolved"]:
            bv = bd.get(k, 0.0)
            gv = gd.get(k, 0.0)
            print(f"  {k:<18} {bv:>12.3f} {gv:>12.3f}")
    else:
        print("[无落盘对照数据]")
        print(f"  需先运行流水线生成 {baseline_path} 和 {grounded_path}。")
        print("  可通过集成测试或手动触发 run_pipeline 产出。")


if __name__ == "__main__":
    main()
