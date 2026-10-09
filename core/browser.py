"""Edge 会话管理：CDP 就绪检查 / 按需拉起专用实例"""

import subprocess
import time
from pathlib import Path

import httpx

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

BG_FLAGS = [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]


def find_msedge():
    for p in EDGE_CANDIDATES:
        if Path(p).exists():
            return p
    raise FileNotFoundError("msedge.exe not found in standard paths")


def cdp_alive(port, timeout=2.0):
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def ensure_edge(port, profile_dir, log, launch=True, wait_sec=45, background=False):
    """返回 'attached' 或 'launched'；启动失败抛异常"""
    if cdp_alive(port):
        log(f"[edge] CDP already up on :{port}")
        return "attached"
    if not launch:
        raise RuntimeError("CDP not reachable and launch_on_demand=false")
    edge = find_msedge()
    profile_dir = str(profile_dir)
    args = [
        edge,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "https://cn.bing.com",
    ]
    if background:
        args.extend(BG_FLAGS)
    log(f"[edge] launching: {edge}")
    subprocess.Popen(args)
    t0 = time.time()
    while time.time() - t0 < wait_sec:
        if cdp_alive(port):
            log(f"[edge] CDP up after {time.time() - t0:.1f}s")
            return "launched"
        time.sleep(1.5)
    raise RuntimeError("Edge CDP did not come up in time")


def minimize_window(ctx, log):
    """把专用 Edge 窗口最小化（后台模式）"""
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        cdp = ctx.new_cdp_session(page)
        info = cdp.send("Browser.getWindowForTarget")
        cdp.send("Browser.setWindowBounds", {
            "windowId": info["windowId"],
            "bounds": {"windowState": "minimized"}})
        cdp.detach()
        log("[edge] window minimized (background mode)")
    except Exception as e:
        log(f"[edge] minimize skipped: {str(e)[:120]}")
