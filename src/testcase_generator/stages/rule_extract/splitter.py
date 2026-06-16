"""章节树切分器 —— 把 PRD 原始 markdown 沿标题树切成「规则抽取单元」。

固化自离线探针 `.qa_probe/rule_extract/extract_rules.py`（已修 EOF 越界 bug）。纯函数：
输入原始 markdown 字符串，输出 `(units, digest, classify_log)`，不依赖 DB/LLM/文件系统。

策略：
  ① 沿 markdown 章节树（#/##）切「模块单元」，超长大块再按 ### 细切；
  ② meta（文档元信息/变更日志/版本日志…）整树丢弃，不抽规则；
  ③ digest（背景/目标/概览/术语…）不单独抽规则，但汇成全局摘要喂给各单元；
  ④ 正文过短（纯标题/导航占位）的块跳过。
"""

from __future__ import annotations

import re

from pydantic import BaseModel

# 单元字符上限：超过则按下一级标题细切，保证「单窗口高保真 + 不超长」
UNIT_MAX_CHARS = 7000
# 正文太短的块视为导航/标题占位，不进规则抽取
MIN_BODY_CHARS = 80

# meta：完全丢弃（不抽规则）
_META_KW = (
    "文档元信息", "文档版本", "变更日志", "变更记录", "修订记录", "修订历史",
    "版本日志", "版本历史", "版本记录", "评审记录",
)
# digest：不单独抽规则，但作为全局摘要喂给每个规则单元
_DIGEST_KW = ("需求背景", "预期目标", "概览", "名词解释", "术语", "范围", "目标")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def _clean_title(raw: str) -> str:
    return raw.replace("*", "").replace("`", "").strip()


def _classify(title: str) -> str:
    t = _clean_title(title)
    if any(k in t for k in _META_KW):
        return "meta"
    if any(k in t for k in _DIGEST_KW):
        return "digest"
    return "rule"


class Heading(BaseModel):
    level: int
    title: str
    line: int


def _parse_headings(lines: list[str]) -> list[Heading]:
    hs: list[Heading] = []
    for i, ln in enumerate(lines):
        m = _HEADING_RE.match(ln)
        if m:
            hs.append(Heading(level=len(m.group(1)), title=_clean_title(m.group(2)), line=i))
    return hs


def _block_text(lines: list[str], start: int, end: int) -> str:
    return "\n".join(lines[start:end]).strip()


def _split_blocks(
    lines: list[str], headings: list[Heading], level_cut: int, end_bound: int | None = None
) -> list[dict]:
    """在 level<=level_cut 的标题处切块；每块覆盖到下一个 level<=level_cut 标题之前。

    end_bound：最后一块的右边界（行号）。细切子块时必须传父块的 end_line，否则最后一个
    子块会一路吃到整个文件结尾（EOF 越界 bug）。
    """
    bound = end_bound if end_bound is not None else len(lines)
    cut_idx = [h for h in headings if h.level <= level_cut]
    blocks: list[dict] = []
    for k, h in enumerate(cut_idx):
        end_line = cut_idx[k + 1].line if k + 1 < len(cut_idx) else bound
        text = _block_text(lines, h.line, end_line)
        body = _block_text(lines, h.line + 1, end_line)
        has_children = any(h.line < hh.line < end_line and hh.level > h.level for hh in headings)
        blocks.append({
            "title": h.title, "level": h.level, "line": h.line, "end_line": end_line,
            "text": text, "body": body, "chars": len(text), "has_children": has_children,
        })
    return blocks


def _char_window(text: str, size: int) -> list[str]:
    """超大叶子单元的兜底：按行累积切成 <=size 的字符窗，避免单次输入过长。"""
    out, cur = [], ""
    for ln in text.splitlines(keepends=True):
        if cur and len(cur) + len(ln) > size:
            out.append(cur)
            cur = ""
        cur += ln
    if cur.strip():
        out.append(cur)
    return out or [text]


def _emit_unit(units: list[dict], title: str, level: int, text: str) -> None:
    """落单元；超大叶子按字符窗兜底切分。"""
    if len(text) <= UNIT_MAX_CHARS * 1.4:
        units.append({"title": title, "level": level, "chars": len(text), "text": text})
        return
    windows = _char_window(text, UNIT_MAX_CHARS)
    for i, w in enumerate(windows, 1):
        units.append({
            "title": f"{title} (片段{i}/{len(windows)})", "level": level,
            "chars": len(w), "text": w,
        })


def build_units(md: str) -> tuple[list[dict], str, list[dict]]:
    """把原始 markdown 切成规则单元。

    Returns:
        (rule_units, digest, classify_log)
        - rule_units: [{title, level, chars, text}]，每个是喂给抽取器的「模块全文」单元
        - digest: 全局摘要（背景/目标/术语等），各单元共享
        - classify_log: [{title, level, chars, kind}]，切分诊断
    """
    lines = md.splitlines()
    headings = _parse_headings(lines)

    # 一级切块（# 和 ##）
    blocks = _split_blocks(lines, headings, level_cut=2)

    classify_log: list[dict] = []
    digest_parts: list[str] = []
    rule_units: list[dict] = []

    for b in blocks:
        kind = _classify(b["title"])
        classify_log.append({"title": b["title"], "level": b["level"], "chars": b["chars"], "kind": kind})

        if kind == "meta":
            continue
        if kind == "digest":
            digest_parts.append(f"【{b['title']}】\n{b['body'][:1200]}")
            continue
        # rule 单元：正文太短（纯章节标题/导语）一律跳过，无可抽取内容
        if len(b["body"]) < MIN_BODY_CHARS:
            continue
        if b["chars"] <= UNIT_MAX_CHARS or not b["has_children"]:
            _emit_unit(rule_units, b["title"], b["level"], b["text"])
        else:
            # 大块按 ### 细切（end_bound 必须传父块右边界，修 EOF 越界）
            sub_headings = [h for h in headings if b["line"] <= h.line < b["end_line"]]
            subs = _split_blocks(lines, sub_headings, level_cut=3, end_bound=b["end_line"])
            for s in subs:
                if _classify(s["title"]) == "meta" or len(s["body"]) < MIN_BODY_CHARS:
                    continue
                title = f"{b['title']} › {s['title']}" if s["title"] != b["title"] else b["title"]
                _emit_unit(rule_units, title, s["level"], s["text"])

    digest = "\n\n".join(digest_parts)[:2500]
    return rule_units, digest, classify_log
