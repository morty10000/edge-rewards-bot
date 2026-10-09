# 在脚本专用 Edge 中打开看板，并恢复窗口可见（演示/查看用）
# Run: .venv\Scripts\python open_dashboard.py

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402


def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    port = cfg["edge"]["port"]
    dash = cfg.get("dashboard", {}).get("port", 17173)
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = b.contexts[0]
        pg = ctx.new_page()
        pg.goto(f"http://127.0.0.1:{dash}/", wait_until="domcontentloaded", timeout=30000)
        pg.bring_to_front()
        cdp = ctx.new_cdp_session(pg)
        info = cdp.send("Browser.getWindowForTarget")
        cdp.send("Browser.setWindowBounds", {
            "windowId": info["windowId"],
            "bounds": {"windowState": "maximized"}})
        cdp.detach()
        print("dashboard opened in bot Edge window (maximized)")


if __name__ == "__main__":
    main()
