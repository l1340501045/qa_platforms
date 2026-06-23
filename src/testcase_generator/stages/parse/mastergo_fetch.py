"""落点⑦ — MasterGo 原型 DSL 规格接入。检测 PRD 里的 mastergo 链接 → 拉 DSL → 抽规格摘要 → 并入章节内容。

宽进严出：
- /file/ 直链带 layer_id → 直接取 DSL（最优路径）
- /file/ 直链仅 page_id → 尝试取 DSL，空 nodes 跳过并提示贴 Frame 级链接
- /goto/ 短链 → 跟随 302 重定向解析目标 URL，再走上述逻辑
- 无链接/无 token/失败均安全跳过，绝不阻断解析
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_DSL_URL = "https://mastergo.com/mcp/dsl"
_FILE_RE = re.compile(r"https?://mastergo\.com/file/(\d+)[^\s)\]]*", re.I)
_GOTO_RE = re.compile(r"https?://mastergo\.com/goto/[^\s)\]]+", re.I)
_LAYER_RE = re.compile(r"[?&]layer_id=([^&\s)\]]+)", re.I)
_PAGE_RE = re.compile(r"[?&]page_id=([^&\s)\]]+)", re.I)
_TIMEOUT = 30
_MAX_DIGEST = 4000


@dataclass(frozen=True)
class MgRef:
    url: str
    file_id: str
    layer_id: str  # 具体 Frame/图层 ID（最优）或 page_id（降级尝试）
    is_page_only: bool  # True = 仅有 page_id，DSL 可能返回空


def _decode_param(raw: str) -> str:
    """URL 解码参数值（如 90%3A420043 → 90:420043）。"""
    return httpx.URL(f"http://x/?v={raw}").params.get("v") or raw


def extract_mastergo_links(content: str) -> list[MgRef]:
    """从文本抽 MasterGo /file/ 链接。同时识别 layer_id 和 page_id。无则 []。"""
    refs: list[MgRef] = []
    seen: set[tuple[str, str]] = set()
    for m in _FILE_RE.finditer(content or ""):
        url = m.group(0)
        file_id = m.group(1)
        lm = _LAYER_RE.search(url)
        pm = _PAGE_RE.search(url)
        if lm:
            target_id = _decode_param(lm.group(1))
            is_page_only = False
        elif pm:
            target_id = _decode_param(pm.group(1))
            is_page_only = True
        else:
            continue
        key = (file_id, target_id)
        if key in seen:
            continue
        seen.add(key)
        refs.append(MgRef(url=url, file_id=file_id, layer_id=target_id, is_page_only=is_page_only))
    return refs


def extract_goto_links(content: str) -> list[str]:
    """从文本抽 /goto/ 短链 URL。"""
    return _GOTO_RE.findall(content or "")


def dsl_to_spec_digest(dsl: dict, max_chars: int = _MAX_DIGEST) -> str:
    """遍历 DSL，按屏/容器分组抽 TEXT 文本，去重输出可读摘要。空则 ''。"""
    nodes = (dsl or {}).get("nodes") or []

    def texts_of(node: dict, acc: list[str]) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "TEXT":
            s = "".join(seg.get("text", "") for seg in (node.get("text") or []) if isinstance(seg, dict)).strip()
            if s:
                acc.append(s)
        for c in node.get("children") or []:
            texts_of(c, acc)

    screens: list[tuple[str, list[str]]] = []
    for top in nodes:
        children = top.get("children") or [top]
        for screen in children:
            acc: list[str] = []
            texts_of(screen, acc)
            if acc:
                screens.append((screen.get("name") or "screen", acc))

    seen: set[str] = set()
    lines: list[str] = []
    for name, acc in screens:
        uniq = [t for t in acc if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]
        if uniq:
            lines.append(f"· {name}：" + " / ".join(uniq))
    return "\n".join(lines)[:max_chars]


async def resolve_goto(url: str) -> list[MgRef]:
    """GET /goto/ 短链，跟随 302 解析目标 URL 中的 MgRef。失败返回 []。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            resp = await client.get(url)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                return extract_mastergo_links(location)
    except Exception as e:  # noqa: BLE001
        logger.warning("MasterGo /goto/ 短链解析失败，跳过 %s: %s", url, e)
    return []


async def fetch_dsl(file_id: str, layer_id: str, token: str) -> dict:
    """调官方 DSL 接口。抛异常由调用方兜底。"""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-MG-UserAccessToken": token,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(_DSL_URL, params={"fileId": file_id, "layerId": layer_id}, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def enrich_sections_with_mastergo(sources: list, token: str) -> int:
    """原地：把每个 section 内容里的 MasterGo 原型规格摘要追加进该 section.content。
    返回成功富化的链接数。单链接失败跳过、记日志、不抛。
    文档级缓存：同一 (file_id, layer_id) 只拉一次。
    """
    if not token:
        return 0
    enriched = 0
    cache: dict[tuple[str, str], str] = {}  # (file_id, layer_id) → digest

    for src in sources:
        for sec in getattr(src, "sections", []) or []:
            content = sec.content or ""
            refs = extract_mastergo_links(content)

            # /goto/ 短链：解析重定向获取真实 refs
            for goto_url in extract_goto_links(content):
                resolved = await resolve_goto(goto_url)
                refs.extend(resolved)

            for ref in refs:
                cache_key = (ref.file_id, ref.layer_id)
                if cache_key in cache:
                    digest = cache[cache_key]
                else:
                    try:
                        dsl = await fetch_dsl(ref.file_id, ref.layer_id, token)
                        digest = dsl_to_spec_digest(dsl)
                        cache[cache_key] = digest
                        if not digest and ref.is_page_only:
                            logger.info(
                                "MasterGo page 级链接 DSL 为空（需贴 Frame 级链接才能获取规格）: %s",
                                ref.url,
                            )
                    except Exception as e:  # noqa: BLE001
                        logger.warning("MasterGo 原型拉取失败，跳过 %s: %s", ref.url, e)
                        cache[cache_key] = ""
                        continue
                if digest:
                    sec.content = (sec.content or "") + f"\n\n【原型规格（来自 MasterGo 设计稿）】\n{digest}"
                    enriched += 1
    if enriched:
        logger.info("MasterGo 原型规格已并入 %d 个链接", enriched)
    return enriched
