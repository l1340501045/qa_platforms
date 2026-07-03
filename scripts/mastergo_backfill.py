"""落点⑦ 存量迁移工具：扫老 PRD → 抓 MasterGo 原型规格 → 幂等回灌进 documents.content。

为什么是独立工具：MasterGo 将下线、后续 PRD 基本不再用它，但存量 PRD 需沉淀。
不进生成热路径，一次性跑。详见 docs/plans/2026-06-23-mastergo-prototype-source-plan.md。

子命令：
  login                          一次性 headed 登录，持久化会话到 --session-dir
  scan                           列出 content 含 mastergo.com 的 PRD
  run --doc <uuid> [--apply]     抓规格并回灌（默认 dry-run 只预览不写库）
  run --all [--apply]            对所有含链接的 PRD 批处理

token 解析：--token > settings.mastergo_api_token（env MASTERGO_API_TOKEN）
会话目录：--session-dir，默认 .mastergo_session（已 gitignore）

用法示例：
  uv run python scripts/mastergo_backfill.py login
  uv run python scripts/mastergo_backfill.py scan
  uv run python scripts/mastergo_backfill.py run --doc <uuid>           # 预览
  uv run python scripts/mastergo_backfill.py run --doc <uuid> --apply   # 落库
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.platform_api.core.settings import settings  # noqa: E402
from src.testcase_generator.stages.parse.mastergo_fetch import (  # noqa: E402
    build_backfill_block,
    dsl_to_spec_digest,
    extract_goto_links,
    extract_mastergo_links,
    fetch_dsl,
    filter_promo_digests,
    inject_backfill_block,
    resolve_goto,
)

logger = logging.getLogger("mastergo_backfill")

_SESSION_DEFAULT = ".mastergo_session"
# 登录引导文案：出现即未登录（落地页/弹窗）
_NAG = ("免费注册", "扫码登录", "密码登录", "获取验证码", "注册登录后查看", "登录后查看最新设计稿")

# 滚动图层面板、收集顶层帧 layer_id（data-offsetleft==0）。已在 .qa_probe/mastergo_enum.py 实测。
_JS_COLLECT = r"""
async () => {
  const match = (s) => /^\d+:\d+$/.test(s || '');
  const collect = (set) => {
    document.querySelectorAll('[data-id]').forEach(e => {
      const d = e.getAttribute('data-id');
      const off = e.getAttribute('data-offsetleft');
      if (match(d)) set.add(JSON.stringify({ id: d, off: off }));
    });
  };
  let cont = null;
  const samp = document.querySelector('[nodename]');
  if (samp) {
    let el = samp.parentElement;
    while (el) {
      if (el.scrollHeight > el.clientHeight + 20) { cont = el; break; }
      el = el.parentElement;
    }
  }
  const set = new Set();
  collect(set);
  if (cont) {
    for (let y = 0; y <= cont.scrollHeight + cont.clientHeight; y += Math.max(80, cont.clientHeight - 60)) {
      cont.scrollTop = y;
      await new Promise(r => setTimeout(r, 300));
      collect(set);
    }
  }
  return { rows: [...set].map(s => JSON.parse(s)) };
}
"""


class MgNotLoggedInError(RuntimeError):
    """登录态缺失/过期，需重新 login。"""


def _resolve_token(arg_token: str | None) -> str:
    token = arg_token or settings.mastergo_api_token
    if not token:
        raise SystemExit("缺少 MasterGo token：用 --token 或在 .env 配 MASTERGO_API_TOKEN")
    return token


# ── 浏览器枚帧器 ───────────────────────────────────────────────────────────
async def harvest_frame_ids(file_id: str, page_id: str, session_dir: str, headless: bool = True) -> list[str]:
    """page_id → 该页顶层 frame layer_id 列表。读图层面板 DOM。未登录抛 MgNotLoggedIn。"""
    from playwright.async_api import async_playwright

    url = f"https://mastergo.com/file/{file_id}?page_id={quote(page_id)}"
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            session_dir, headless=headless, viewport={"width": 1680, "height": 1000}
        )
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=60000)
            except Exception:  # noqa: BLE001 — 首屏可能跳转，继续轮询面板
                pass
            panel = None
            for _ in range(20):
                panel = await page.query_selector("[nodename]")
                if panel:
                    break
                await asyncio.sleep(2)
            await asyncio.sleep(4)
            if not panel:
                body = ""
                try:
                    body = await page.inner_text("body", timeout=4000)
                except Exception:  # noqa: BLE001
                    pass
                if any(t in body for t in _NAG):
                    raise MgNotLoggedInError("MasterGo 未登录或会话过期，请先跑 `login`")
                logger.warning("图层面板未出现，文档可能无可读页面: %s", url)
                return []
            res = await page.evaluate(_JS_COLLECT)
        finally:
            await ctx.close()
    rows = res.get("rows", []) if isinstance(res, dict) else []
    return [r["id"] for r in rows if r.get("off") == "0" and r.get("id")]


# ── 编排：链接 → 规格 ──────────────────────────────────────────────────────
def _screen_name(digest: str) -> str:
    first = digest.splitlines()[0] if digest else ""
    if first.startswith("· ") and "：" in first:
        return first[2:].split("：", 1)[0].strip()
    return ""


async def resolve_specs(content: str, token: str, session_dir: str, headless: bool = True) -> dict[str, str]:
    """content 内所有 MasterGo 链接 → {链接: 规格摘要}。page_id 走浏览器枚帧；layer_id 直取。"""
    refs = list(extract_mastergo_links(content))
    for goto_url in extract_goto_links(content):
        refs.extend(await resolve_goto(goto_url))

    out: dict[str, str] = {}
    frame_cache: dict[tuple[str, str], str] = {}
    for ref in refs:
        if ref.url in out:
            continue
        try:
            if ref.is_page_only:
                ids = await harvest_frame_ids(ref.file_id, ref.layer_id, session_dir, headless=headless)
            else:
                ids = [ref.layer_id]
            items: list[tuple[str, str]] = []
            for fid in ids:
                ck = (ref.file_id, fid)
                if ck in frame_cache:
                    dig = frame_cache[ck]
                else:
                    try:
                        dsl = await fetch_dsl(ref.file_id, fid, token)
                        dig = dsl_to_spec_digest(dsl)
                    except Exception as e:  # noqa: BLE001 — 单帧失败跳过
                        logger.warning("getDsl 失败 %s/%s: %s", ref.file_id, fid, e)
                        dig = ""
                    frame_cache[ck] = dig
                if dig:
                    items.append((_screen_name(dig) or fid, dig))
            kept = filter_promo_digests(items)
            if kept:
                out[ref.url] = "\n\n".join(d for _n, d in kept)
        except MgNotLoggedInError:
            raise
        except Exception as e:  # noqa: BLE001 — 单链接失败跳过，不中断整批
            logger.warning("链接处理失败，跳过 %s: %s", ref.url, e)
    return out


# ── 子命令 ─────────────────────────────────────────────────────────────────
async def cmd_login(session_dir: str) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            session_dir, headless=False, viewport={"width": 1680, "height": 1000}
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto("https://mastergo.com/", wait_until="domcontentloaded", timeout=40000)
        except Exception:  # noqa: BLE001
            pass
        print(">>> 浏览器已打开，请登录 MasterGo（手机号/验证码或扫码）。登录后无需操作，会自动保存会话。")
        clean = 0
        for _ in range(45):  # 最多 ~180s
            try:
                body = await page.inner_text("body", timeout=3000)
            except Exception:  # noqa: BLE001
                body = ""
            if body and not any(t in body for t in _NAG):
                clean += 1
                if clean >= 2:
                    print(">>> 检测到已登录，保存会话。")
                    break
            else:
                clean = 0
            await asyncio.sleep(4)
        else:
            print(">>> 超时未确认登录状态；若你已登录，会话仍会保存（可直接 run 试）。")
        await ctx.close()
    print(f">>> 会话已保存到 {session_dir}")


async def _iter_link_docs(session, only_id: UUID | None):
    from sqlalchemy import select

    from src.platform_api.models.knowledge import Document

    stmt = select(Document.id, Document.title).where(Document.deleted_at.is_(None))
    if only_id is not None:
        stmt = stmt.where(Document.id == only_id)
    else:
        stmt = stmt.where(Document.content.like("%mastergo.com%"))
    return (await session.execute(stmt)).all()


async def cmd_scan() -> None:
    from src.knowledge_base.db import async_session_factory
    from src.knowledge_base.repositories.document_repo import DocumentRepository

    async with async_session_factory() as s:
        rows = await _iter_link_docs(s, None)
        repo = DocumentRepository(s)
        for did, title in rows:
            doc = await repo.get_by_id(did)
            content = doc.content if doc else ""
            n = len(extract_mastergo_links(content)) + len(extract_goto_links(content))
            print(f"{did}  links={n}  {title}")
    print(f"\n共 {len(rows)} 个文档 content 含 mastergo.com")


async def cmd_run(
    doc_ids: list[UUID] | None,
    all_docs: bool,
    token: str,
    session_dir: str,
    apply: bool,
    backup: bool,
    headless: bool,
) -> None:
    from src.knowledge_base.db import async_session_factory
    from src.knowledge_base.repositories.document_repo import DocumentRepository
    from src.knowledge_base.services.embedding.vectorize_pipeline import VectorizePipeline

    async with async_session_factory() as s:
        repo = DocumentRepository(s)
        if all_docs:
            targets = [did for did, _title in await _iter_link_docs(s, None)]
        else:
            targets = doc_ids or []
        print(f">>> 目标文档 {len(targets)} 个；模式：{'APPLY 落库' if apply else 'DRY-RUN 预览'}\n")

        for did in targets:
            doc = await repo.get_by_id(did)
            if not doc or not doc.content:
                print(f"[skip] {did} 无内容")
                continue
            try:
                specs = await resolve_specs(doc.content, token, session_dir, headless=headless)
            except MgNotLoggedInError as e:
                print(f"[stop] {e}")
                return
            if not specs:
                print(f"[skip] {did}  {doc.title} — 未抽到规格（无有效链接/帧）")
                continue

            block = build_backfill_block(specs)
            new_content = inject_backfill_block(doc.content, block)
            added = len(new_content) - len(doc.content)
            print(f"=== {did}  {doc.title} ===")
            print(f"抽到 {len(specs)} 个原型链接的规格；注入净增 {added} 字")
            print("--- 回灌块预览（前 800 字）---")
            print(block[:800])
            print("--- /预览 ---")

            if apply:
                if backup:
                    bak = Path(f"backup_{did}.content.md")
                    bak.write_text(doc.content, encoding="utf-8")
                    print(f"[backup] 原文已存 {bak}")
                content_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
                await repo.update(did, content=new_content, content_hash=content_hash)
                await s.commit()
                await VectorizePipeline(s).vectorize_document(did)
                await s.commit()
                print(f"[applied] content_hash={content_hash[:12]}… 已重嵌\n")
            else:
                print("[dry-run] 未写库（加 --apply 落库）\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="MasterGo 存量原型规格迁移工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="一次性 headed 登录，持久化会话")
    p_login.add_argument("--session-dir", default=_SESSION_DEFAULT)

    sub.add_parser("scan", help="列出含 MasterGo 链接的 PRD")

    p_run = sub.add_parser("run", help="抓规格并回灌")
    g = p_run.add_mutually_exclusive_group(required=True)
    g.add_argument("--doc", action="append", help="目标文档 UUID（可多次）")
    g.add_argument("--all", action="store_true", help="所有含链接文档")
    p_run.add_argument("--apply", action="store_true", help="落库（默认 dry-run）")
    p_run.add_argument("--backup", action="store_true", help="apply 前把原文备份到文件")
    p_run.add_argument("--headful", action="store_true", help="枚帧时显示浏览器（调试）")
    p_run.add_argument("--session-dir", default=_SESSION_DEFAULT)
    p_run.add_argument("--token", default=None)

    args = parser.parse_args()

    if args.cmd == "login":
        asyncio.run(cmd_login(args.session_dir))
    elif args.cmd == "scan":
        asyncio.run(cmd_scan())
    elif args.cmd == "run":
        token = _resolve_token(args.token)
        doc_ids = [UUID(d) for d in args.doc] if args.doc else None
        asyncio.run(
            cmd_run(
                doc_ids=doc_ids,
                all_docs=args.all,
                token=token,
                session_dir=args.session_dir,
                apply=args.apply,
                backup=args.backup,
                headless=not args.headful,
            )
        )


if __name__ == "__main__":
    main()
