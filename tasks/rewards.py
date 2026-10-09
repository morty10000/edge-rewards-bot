"""积分面板（flyout）操作：状态读取 / 领取 / 每日活动

全部通过 CDP 驱动真实 Edge 的 UI 完成；
文本标记与正则来自 selectors.yaml，改版时优先改配置。
"""

import re
import time
from pathlib import Path

import yaml
from playwright.sync_api import TimeoutError as PWTimeout

ROOT = Path(__file__).resolve().parent.parent
SEL = yaml.safe_load((ROOT / "selectors.yaml").read_text(encoding="utf-8"))


def open_flyout(ctx, timeout=45000, settle=7):
    page = ctx.new_page()
    page.goto(SEL["flyout_url"], wait_until="domcontentloaded", timeout=timeout)
    time.sleep(settle)
    return page


def reload_flyout(page, settle=6):
    page.reload(wait_until="domcontentloaded")
    time.sleep(settle)


def check_block(page):
    """风控信号检测：命中返回信号词，未命中返回 None"""
    try:
        txt = page.inner_text("body")[:20000]
    except Exception:
        return None
    for sig in SEL.get("block_signals", []):
        if sig and sig in txt:
            return sig
    return None


def read_cards(page):
    js = """(sel) => [...document.querySelectorAll(sel)].map(a => ({
        href: a.href,
        text: (a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 220),
        done: (a.textContent || '').includes('已完成')
    }))"""
    try:
        return page.evaluate(js, SEL["card_link_selector"])
    except Exception:
        return []


def read_state(page):
    txt = page.inner_text("body")
    st = {}
    m = re.search(r"([\d,]+)\s*\n分", txt)
    st["balance"] = int(m.group(1).replace(",", "")) if m else None
    m = re.search(SEL["pending_regex"], txt)
    st["pending"] = int(m.group(1)) if m else 0
    for key, sel_key in (("search", "search_streak_regex"),
                         ("dailyset", "dailyset_streak_regex"),
                         ("app", "app_streak_regex")):
        m = re.search(SEL[sel_key], txt)
        st[key] = {"done": int(m.group(1)), "total": int(m.group(2))} if m else None
    st["cards"] = read_cards(page)
    st["cards_undone"] = sum(1 for c in st["cards"] if not c["done"])
    return st


def claim_pending(page, cfg, log):
    """点击领取待领取积分；返回领取前的待领数量（0 表示没有）"""
    txt = page.inner_text("body")
    m = re.search(SEL["pending_regex"], txt)
    if not m:
        log("[claim] no pending points")
        return 0
    amount = int(m.group(1))
    try:
        page.get_by_text(SEL["claim_button_text"], exact=True).first.click(timeout=8000)
    except PWTimeout:
        page.locator(f"button:has-text('{SEL['pending_button_text']}')").first.click(timeout=5000)
    time.sleep(4)
    try:
        if page.locator("[role=dialog]").count() > 0:
            for t in (SEL["claim_button_text"], "确认", "确定", "继续"):
                loc = page.locator(f"[role=dialog] button:has-text('{t}')")
                if loc.count():
                    loc.first.click(timeout=3000)
                    log(f"[claim] dialog confirmed: {t}")
                    break
            time.sleep(cfg["humanize"]["post_claim_wait_sec"])
    except Exception as e:
        log(f"[claim] dialog err: {str(e)[:120]}")
    log(f"[claim] claimed {amount} points")
    return amount


def _click_card(ctx, page, card, log):
    """优先 JS 点击（保留 href 触发真实跳转），失败回退真实点击"""
    href = card["href"]
    try:
        with ctx.expect_page(timeout=20000) as ev:
            page.evaluate(
                """href => {
                    const a = [...document.querySelectorAll('a')].find(x => x.href === href);
                    if (a) { a.scrollIntoView({block: 'center'}); a.click(); }
                }""", href)
        np = ev.value
        np.wait_for_load_state("domcontentloaded", timeout=45000)
        time.sleep(7)
        try:
            np.mouse.wheel(0, 500)
            time.sleep(2)
        except Exception:
            pass
        np.close()
        return True
    except Exception as e:
        log(f"[activity] js-click failed: {str(e)[:100]}, fallback to real click")
    try:
        snippet = re.sub(r"\s+", "", card["text"])[:8]
        with ctx.expect_page(timeout=20000) as ev:
            page.locator("a").filter(has_text=snippet).first.click(timeout=8000)
        np = ev.value
        np.wait_for_load_state("domcontentloaded", timeout=45000)
        time.sleep(7)
        np.close()
        return True
    except Exception as e:
        log(f"[activity] real-click failed: {str(e)[:100]}")
        return False


def do_activities(ctx, page, cfg, log):
    """逐个完成未完成的每日活动卡；返回（本次完成标题列表, 最终状态）"""
    retry = int(cfg["rewards"]["verify_retry"])
    finished = []
    for rnd in range(retry + 1):
        undone = [c for c in read_cards(page) if not c["done"]]
        if not undone:
            break
        for c in undone:
            title = c["text"][:26]
            log(f"[activity] open: {title}")
            _click_card(ctx, page, c, log)
            time.sleep(8)
            reload_flyout(page)
            st = read_state(page)
            still = any((not x["done"]) and x["href"] == c["href"] for x in st["cards"])
            if not still:
                finished.append(title)
                log(f"[activity] DONE: {title}")
            else:
                log(f"[activity] not counted yet: {title}")
            cfg_gap = cfg["humanize"]["click_gap_sec"]
            time.sleep(cfg_gap[0] + (cfg_gap[1] - cfg_gap[0]) * 0.4)
    reload_flyout(page)
    return finished, read_state(page)
