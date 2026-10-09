"""搜索积分：热点词抓取 + 拟人化搜索 + 计数校验"""

import base64
import json
import random
import re
import time
from pathlib import Path

import yaml
from playwright.sync_api import TimeoutError as PWTimeout

ROOT = Path(__file__).resolve().parent.parent
SEL = yaml.safe_load((ROOT / "selectors.yaml").read_text(encoding="utf-8"))


def get_hot_queries(page, log, limit=30):
    """从必应首页抓「必应上的热点」，作为自然查询词"""
    try:
        page.goto(SEL["home_url"], wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)
        qs = page.evaluate("""() => {
            const out = [];
            const seen = new Set();
            for (const a of document.querySelectorAll('a')) {
                const t = (a.textContent || '').trim();
                if (!a.href || !a.href.includes('/search?q=')) continue;
                if (t.length < 4 || t.length > 32) continue;
                if (seen.has(t)) continue;
                seen.add(t);
                out.push(t);
                if (out.length >= 40) break;
            }
            return out;
        }""")
        cleaned, seen = [], set()
        for q in qs:
            q = re.sub(r"^\d+[\.\u3001\s]*", "", q).strip()     # 去掉序号前缀
            if not q or len(q) < 4 or q in seen:
                continue
            if any(k in q for k in ("必应上的热点", "热搜", "热点")) and len(q) <= 8:
                continue
            seen.add(q)
            cleaned.append(q)
        log(f"[search] hot queries: {len(cleaned)}")
        return cleaned[:limit]
    except Exception as e:
        log(f"[search] hot scrape failed: {str(e)[:120]}")
        return []


def read_medallion_balance(page):
    """从首页/结果页勋章 data-content（base64 JSON）读余额"""
    try:
        b64 = page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                return el ? el.getAttribute('data-content') : null;
            }""", SEL["medallion_selector"])
        if not b64:
            return None
        pad = b64 + "=" * (-len(b64) % 4)
        cfg = json.loads(base64.b64decode(pad))
        return cfg.get("balance")
    except Exception:
        return None


def _do_one_search(page, query, cfg, log):
    page.goto(SEL["home_url"], wait_until="domcontentloaded", timeout=45000)
    time.sleep(random.uniform(2, 4))
    page.click(SEL["search_box_selector"], timeout=8000)
    page.locator(SEL["search_box_selector"]).press_sequentially(
        query, delay=random.randint(60, 140), timeout=15000)
    time.sleep(random.uniform(0.5, 1.2))
    page.keyboard.press("Enter")
    page.wait_for_load_state("domcontentloaded", timeout=45000)
    d = cfg["search"]["dwell_sec"]
    time.sleep(random.uniform(d[0], d[1]))
    try:
        page.mouse.wheel(0, random.randint(300, 900))
        time.sleep(random.uniform(1, 3))
    except Exception:
        pass


def run_searches(page, queries, cfg, log, count_override=None):
    """返回 {done, balances, notes}"""
    sc = cfg["search"]
    count = int(count_override or sc["count"])
    waves = max(1, int(sc["waves"]))
    per = [count // waves + (1 if i < count % waves else 0) for i in range(waves)]
    bank = sc.get("query_bank") or []
    queries = list(queries) or []
    done, balances, notes = 0, [], []
    empty_streak = 0

    for w, n in enumerate(per):
        if n <= 0:
            continue
        log(f"[search] wave {w + 1}/{waves}: {n} searches")
        for _ in range(n):
            q = None
            if queries:
                q = queries[done % len(queries)]
            elif bank:
                q = bank[done % len(bank)]
            if not q:
                notes.append("no queries available")
                break
            try:
                _do_one_search(page, q, cfg, log)
                done += 1
                log(f"[search] #{done}: {q}")
            except Exception as e:
                notes.append(f"search fail: {str(e)[:100]}")
                log(f"[search] fail on {q}: {str(e)[:100]}")
            bal = read_medallion_balance(page)
            if bal is not None:
                balances.append(bal)
                if len(balances) >= 3 and balances[-1] == balances[-2]:
                    empty_streak += 1
                else:
                    empty_streak = 0
                if empty_streak >= int(sc["stop_after_empty"]) and done >= 3:
                    notes.append(f"stop early: no points increase after {done} searches")
                    log(f"[search] early stop (level cap?), balances tail: {balances[-4:]}")
                    return {"done": done, "balances": balances, "notes": notes}
            g = (sc["min_gap_sec"], sc["max_gap_sec"])
            time.sleep(random.uniform(g[0], g[1]))
        if w < waves - 1:
            wg = sc["wave_gap_sec"]
            gap_s = random.uniform(wg[0], wg[1])
            log(f"[search] wave gap: {gap_s:.0f}s")
            time.sleep(gap_s)
    return {"done": done, "balances": balances, "notes": notes}
