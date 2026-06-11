"""dedup 阶段 — 全量用例集上的去重/一致性 pass。

弃"按 feature 孤立审计、漏掉跨功能点重复"的共同盲区：在全量用例上做近重复聚类，
标记 duplicate_of（不删除，交人工裁定），并产出 dedup_summary。
"""
