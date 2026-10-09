#!/usr/bin/env python
"""edge-rewards-bot 主入口

每日任务管线：
  1. 确保 Edge（专用 profile + CDP）就绪
  2. 打开积分面板 → 读取状态 → 领取待领积分
  3. 完成每日活动卡（点击 → 验证 → 必要时重试）
  4. 拟人化搜索（热点词 + 随机节奏 + 上限熔断）
  5. 汇总 / 写入 state.json / 可选通知

Run : .venv\\Scripts\\python main.py [--search-count N] [--no-search] [--no-activities]
"""

import argparse
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import browser, state as state_mod   # noqa: E402
from tasks import rewards, search as search_mod  # noqa: E402
import notify  # noqa: E402


def make_logger(log_path):
    def log(msg):
        line = f"{datetime.now().strftime('%H:%M:%S')} {msg}"
        try:                                   # pythonw(无控制台)下 stdout 为 None
            print(line, flush=True)
        except Exception:
            pass
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return log


def acquire_lock():
    """单实例锁：防止看守触发与定时任务同时跑"""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 49518))
        return s
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--search-count", type=int, default=None)
    ap.add_argument("--no-search", action="store_true")
    ap.add_argument("--no-activities", action="store_true")
    ap.add_argument("--visible", action="store_true",
                    help="不最小化浏览器窗口（调试用）")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    log_dir = ROOT / cfg["run"]["log_dir"]
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"rewards-{datetime.now().strftime('%Y%m%d')}.log"
    log = make_logger(log_path)

    lock = acquire_lock()
    if lock is None:
        log("[lock] another run is in progress; exit")
        return 0

    summary = {"ts": datetime.now().isoformat(timespec="seconds"),
               "date": state_mod.effective_date()}
    log("=" * 60)
    log(f"run start  {summary['ts']}")

    # 1. Edge 就绪
    port = cfg["edge"]["port"]
    browser.ensure_edge(port, ROOT / cfg["edge"]["profile_dir"], log,
                        launch=cfg["edge"]["launch_on_demand"],
                        background=cfg["edge"].get("background", True))

    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = b.contexts[0] if b.contexts else b.new_context()
        if cfg["edge"].get("background", True) and not args.visible:
            browser.minimize_window(ctx, log)

        # 2. 面板：状态 + 领取
        fly = rewards.open_flyout(ctx)
        block = rewards.check_block(fly)
        if block:
            log(f"[SECURITY] block signal detected: {block}; abort")
            summary["blocked"] = block
            fly.close()
        else:
            st0 = rewards.read_state(fly)
            summary["before"] = {"balance": st0["balance"], "pending": st0["pending"]}
            log(f"[state] balance={st0['balance']} pending={st0['pending']} "
                f"search={st0['search']} dailyset={st0['dailyset']} app={st0['app']}")

            claimed = 0
            if cfg["rewards"]["claim_pending"] and st0["pending"] > 0:
                claimed = rewards.claim_pending(fly, cfg, log)
                rewards.reload_flyout(fly)
            summary["claimed"] = claimed

            # 3. 每日活动
            if not args.no_activities and cfg["rewards"]["do_activities"]:
                done, st2 = rewards.do_activities(ctx, fly, cfg, log)
                summary["activities_done"] = done
                summary["dailyset_after"] = st2["dailyset"]
            else:
                summary["activities_done"] = []

            # 4. 搜索
            if not args.no_search and cfg["search"]["enabled"]:
                st_file = ROOT / cfg["run"]["state_file"]
                eff = state_mod.effective_date()
                prev_runs = state_mod.load(st_file).get("runs", [])
                searches_today = sum(
                    int(((r.get("searches") or {}).get("done")) or 0)
                    for r in prev_runs if r.get("date") == eff)
                if (args.search_count is None
                        and searches_today >= int(cfg["search"]["count"])):
                    log(f"[search] {searches_today} searches already done today; skip")
                    summary["searches"] = {"done": 0, "skipped": searches_today}
                else:
                    homes = [pg for pg in ctx.pages
                             if pg.url.startswith("https://cn.bing.com")
                             and "flyout" not in pg.url]
                    home = homes[0] if homes else ctx.new_page()
                    queries = search_mod.get_hot_queries(home, log)
                    if cfg["search"].get("query_source") == "bank":
                        queries = []
                    elif cfg["search"].get("query_source") == "mix" and not queries:
                        queries = []
                    res = search_mod.run_searches(home, queries, cfg, log,
                                                  count_override=args.search_count)
                    summary["searches"] = res

            # 5. 终态（如出现新的待领取，顺手再领一次）
            rewards.reload_flyout(fly)
            st3 = rewards.read_state(fly)
            if st3["pending"] > 0 and cfg["rewards"]["claim_pending"]:
                extra = rewards.claim_pending(fly, cfg, log)
                summary["claimed_extra"] = extra
                rewards.reload_flyout(fly)
                st3 = rewards.read_state(fly)
            summary["streaks"] = {"search": st3["search"], "dailyset": st3["dailyset"],
                                  "app": st3["app"]}
            summary["after"] = {"balance": st3["balance"], "pending": st3["pending"]}
            log(f"[state] final balance={st3['balance']} pending={st3['pending']}")
            try:
                fly.close()
            except Exception:
                pass

    # 6. 汇总
    before = summary.get("before") or {}
    after = summary.get("after") or {}
    delta = None
    if before.get("balance") is not None and after.get("balance") is not None:
        delta = after["balance"] - before["balance"]
    summary["delta"] = delta

    lines = [
        f"日期: {summary['date']}",
        f"余额: {before.get('balance')} -> {after.get('balance')}  (Δ {delta})",
        f"领取: {summary.get('claimed', 0) + summary.get('claimed_extra', 0)} 分",
        f"每日活动完成: {len(summary.get('activities_done', []))} 个",
        f"搜索: {(summary.get('searches') or {}).get('done', 0)} 次",
        f"日志: {log_path.name}",
    ]
    report = "\n".join(lines)
    log("[summary]\n" + report)
    state_mod.record_run(ROOT / cfg["run"]["state_file"], summary)
    notify.send(cfg["notify"].get("webhook_url", ""),
                f"Edge积分 +{delta}", report, log)
    try:
        print("\n" + "=" * 40 + "\n" + report + "\n" + "=" * 40)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
