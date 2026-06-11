"""verify 阶段 — grounding 事实核验关卡

把每条用例对照 PRD 原文逐条核验，判定 grounded/ungrounded/conflict/undefined，
并据此分桶 main/needs_spec/to_fix。核验判据代码固化（rubric.py），保证一致性。
"""
