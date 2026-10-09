# 快速状态检查 — 只读, 不启动 Edge, 不做任何操作
# Run: .venv\Scripts\python status.py

import sys
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import browser  # noqa: E402
from tasks import rewards  # noqa: E402


def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    port = cfg["edge"]["port"]
    if not browser.cdp_alive(port):
        print(f"Edge (bot profile) 未在 CDP :{port} 上运行 — 先跑 launch_edge.ps1 或 main.py")
        return 1
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = b.contexts[0]
        fly = rewards.open_flyout(ctx)
        st = rewards.read_state(fly)
        fly.close()
    print(f"余额:     {st['balance']}")
    print(f"待领取:   {st['pending']}")
    print(f"搜索打卡: {st['search']}")
    print(f"每日活动: {st['dailyset']}   未完成卡: {st['cards_undone']}")
    print(f"应用签到: {st['app']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
