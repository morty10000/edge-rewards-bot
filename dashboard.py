#!/usr/bin/env python
"""Edge 积分看板 — 本地可视化服务（仅标准库 + 项目既存依赖）

Run : .venv\\Scripts\\pythonw.exe dashboard.py
Open: http://127.0.0.1:17173/
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import psutil
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
PORT = int(CFG.get("dashboard", {}).get("port", 17173))
EDGE_PORT = int(CFG["edge"]["port"])
STATE_FILE = ROOT / CFG["run"]["state_file"]

_cache = {"tasks": None, "ts": 0.0}
_NO_WIN = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
_ec = {"v": None, "ts": 0.0}
_wr = {"v": None, "ts": 0.0}
_extseen = {"ts": 0.0}
_live = {"ts": 0.0, "data": None}
_live_lock = threading.Lock()


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"runs": []}


def bot_running():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 49518))
        s.close()
        return False
    except OSError:
        return True


def watcher_running():
    now = time.time()
    if _wr["v"] is not None and now - _wr["ts"] < 10:
        return _wr["v"]
    v = False
    for p in psutil.process_iter(["name"]):
        try:
            if "python" not in (p.info["name"] or "").lower():
                continue
            if "watch_edge" in " ".join(p.cmdline() or []):
                v = True
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _wr["v"], _wr["ts"] = v, now
    return v


def edge_cdp():
    now = time.time()
    if _ec["v"] is not None and now - _ec["ts"] < 5:
        return _ec["v"]
    try:
        v = httpx.get(f"http://127.0.0.1:{EDGE_PORT}/json/version",
                      timeout=1.5).status_code == 200
    except Exception:
        v = False
    _ec["v"], _ec["ts"] = v, now
    return v


def task_info(force=False):
    now = time.time()
    if not force and _cache["tasks"] is not None:
        return _cache["tasks"]          # 请求路径永不阻塞，新鲜度交给后台线程
    items = []
    for name in ("EdgeRewards-AM", "EdgeRewards-PM"):
        try:
            cmd = (
                f"$r=Get-ScheduledTask -TaskName '{name}';"
                f"$i=Get-ScheduledTaskInfo -TaskName '{name}';"
                f"[pscustomobject]@{{name='{name}';state=[string]$r.State;"
                f"next=[string]$i.NextRunTime;result=[long]$i.LastTaskResult}}"
                f"|ConvertTo-Json -Compress")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                                 capture_output=True, text=True, timeout=25,
                                 creationflags=_NO_WIN)
            j = json.loads(out.stdout.strip())
            if j.get("state"):
                items.append(j)
        except Exception:
            pass          # 任务不存在 / 查询失败 → 静默跳过
    _cache["tasks"], _cache["ts"] = items, now
    return items


def ensure_watcher():
    """看守保活：未运行且配置允许时自动拉起（尊重 watch.enabled）"""
    try:
        if not CFG.get("watch", {}).get("enabled", True):
            return
        if watcher_running():
            return
        pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        if not pyw.exists():
            pyw = ROOT / ".venv" / "Scripts" / "python.exe"
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        subprocess.Popen([str(pyw), str(ROOT / "watch_edge.py")],
                         cwd=str(ROOT), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def task_refresher():
    """后台线程：刷新定时任务缓存 + 看守保活"""
    while True:
        try:
            task_info(force=True)
        except Exception:
            pass
        try:
            ensure_watcher()
        except Exception:
            pass
        time.sleep(120)


_wall = {"ts": 0.0, "data": None}
_links = {"ts": 0.0, "data": None}
_wea = {"ts": 0.0, "data": None}


def get_wallpaper():
    """获取必应每日壁纸（缓存 1 小时）"""
    now = time.time()
    if _wall["data"] is not None and now - _wall["ts"] < 3600:
        return _wall["data"]
    try:
        r = httpx.get("https://cn.bing.com/HPImageArchive.aspx",
                      params={"format": "js", "idx": 0, "n": 1, "mkt": "zh-CN"},
                      timeout=12)
        img = (r.json().get("images") or [{}])[0]
        base = img.get("urlbase") or ""
        url = ("https://cn.bing.com" + base + "_1920x1080.jpg") if base else None
        data = {"url": url, "title": img.get("title", ""),
                "copyright": img.get("copyright", "")}
        _wall["data"], _wall["ts"] = data, now
        return data
    except Exception:
        return None


def get_quicklinks():
    """快捷方式: links.json + Edge custom_links + Top Sites（5 分钟缓存）"""
    now = time.time()
    if _links["data"] is not None and now - _links["ts"] < 300:
        return _links["data"]
    items, seen = [], set()

    def add(title, url, icon=None):
        u = str(url or "").strip()
        if not u or u in seen:
            return
        seen.add(u)
        items.append({"title": str(title or u)[:24], "url": u, "icon": icon})

    try:
        data = json.loads((ROOT / "links.json").read_text(encoding="utf-8"))
        for it in (data if isinstance(data, list) else data.get("links", [])):
            add(it.get("title"), it.get("url"), it.get("icon"))
    except Exception:
        pass
    try:
        la = os.environ.get("LOCALAPPDATA", "")
        pref = Path(la) / "Microsoft" / "Edge" / "User Data" / "Default" / "Preferences"
        d = json.loads(pref.read_text(encoding="utf-8", errors="replace"))
        for it in ((d.get("custom_links") or {}).get("list") or []):
            add(it.get("title"), it.get("url"))
    except Exception:
        pass
    try:
        import sqlite3
        la = os.environ.get("LOCALAPPDATA", "")
        db = Path(la) / "Microsoft" / "Edge" / "User Data" / "Default" / "Top Sites"
        if db.exists():
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for url, title in con.execute(
                    "SELECT url, title FROM top_sites ORDER BY url_rank LIMIT 10"):
                add(title, url)
            con.close()
    except Exception:
        pass
    _links["data"], _links["ts"] = items[:12], now
    return _links["data"]


_WMO = {
    0: "晴", 1: "大致晴朗", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    85: "阵雪", 86: "阵雪",
    95: "雷暴", 96: "雷暴冰雹", 99: "雷暴冰雹",
}
_WMO_ICON = {
    0: "\u2600\ufe0f", 1: "\U0001f324\ufe0f", 2: "\u26c5", 3: "\u2601\ufe0f",
    45: "\U0001f32b\ufe0f", 48: "\U0001f32b\ufe0f",
    51: "\U0001f326\ufe0f", 53: "\U0001f326\ufe0f", 55: "\U0001f326\ufe0f",
    56: "\U0001f327\ufe0f", 57: "\U0001f327\ufe0f",
    61: "\U0001f327\ufe0f", 63: "\U0001f327\ufe0f", 65: "\U0001f327\ufe0f",
    66: "\U0001f327\ufe0f", 67: "\U0001f327\ufe0f",
    71: "\U0001f328\ufe0f", 73: "\U0001f328\ufe0f", 75: "\U0001f328\ufe0f",
    77: "\U0001f328\ufe0f",
    80: "\U0001f326\ufe0f", 81: "\U0001f326\ufe0f", 82: "\U0001f327\ufe0f",
    85: "\U0001f328\ufe0f", 86: "\U0001f328\ufe0f",
    95: "\u26c8\ufe0f", 96: "\u26c8\ufe0f", 99: "\u26c8\ufe0f",
}


def get_weather():
    """open-meteo 当前天气（缓存 30 分钟）"""
    now = time.time()
    if _wea["data"] is not None and now - _wea["ts"] < 1800:
        return _wea["data"]
    w = CFG.get("weather", {})
    if not w.get("enabled", True):
        return {}
    try:
        r = httpx.get("https://api.open-meteo.com/v1/forecast",
                      params={"latitude": w.get("lat", 23.02),
                              "longitude": w.get("lon", 113.12),
                              "current": "temperature_2m,weather_code",
                              "timezone": "Asia/Shanghai"},
                      timeout=8)
        cur = r.json().get("current") or {}
        code = int(cur.get("weather_code") or 0)
        data = {"name": w.get("name", ""),
                "temp": cur.get("temperature_2m"),
                "label": _WMO.get(code, ""),
                "icon": _WMO_ICON.get(code, ""),
                "code": code}
        _wea["data"], _wea["ts"] = data, now
        return data
    except Exception:
        return _wea["data"] or {}


def build_state():
    from core.state import effective_date

    st = load_state()
    runs = st.get("runs", [])
    today = effective_date()
    today_runs = [r for r in runs if r.get("date") == today]

    def agg(rs):
        return {
            "delta": sum(int(r.get("delta") or 0) for r in rs),
            "claimed": sum(int(r.get("claimed") or 0) + int(r.get("claimed_extra") or 0)
                           for r in rs),
            "activities": sum(len(r.get("activities_done") or []) for r in rs),
            "searches": sum(int(((r.get("searches") or {}).get("done")) or 0)
                            for r in rs),
            "runs": len(rs),
        }

    by_date = {}
    for r in runs:
        d = r.get("date")
        if not d:
            continue
        e = by_date.setdefault(d, {"date": d, "delta": 0, "claimed": 0, "balance": None})
        e["delta"] += int(r.get("delta") or 0)
        e["claimed"] += int(r.get("claimed") or 0) + int(r.get("claimed_extra") or 0)
        if (r.get("after") or {}).get("balance") is not None:
            e["balance"] = r["after"]["balance"]
    hist = sorted(by_date.values(), key=lambda x: x["date"])[-14:]

    last = runs[-1] if runs else {}
    streaks = last.get("streaks") or {}
    # 跨天快照作废：最近一轮不是"今天"的 → 进度归零（保留卡片总数）
    if last and last.get("date") != today:
        streaks = {k: {"done": 0, "total": (streaks.get(k) or {}).get("total")}
                   for k in ("dailyset", "search", "app")}
    progress = {
        "dailyset": streaks.get("dailyset"),
        "search": streaks.get("search"),
        "app": streaks.get("app"),
        "pending": (last.get("after") or {}).get("pending"),
        "last_ts": last.get("ts"),
        "last_delta": last.get("delta"),
    }

    logf = ROOT / "logs" / f"rewards-{datetime.now().strftime('%Y%m%d')}.log"
    tail = []
    if logf.exists():
        try:
            tail = logf.read_text(encoding="utf-8", errors="replace").splitlines()[-14:]
        except Exception:
            pass

    live = dict(_live["data"]) if (_live["data"] and time.time() - _live["ts"] < 600) else None

    balance, src = None, None
    if live and live.get("balance") is not None:
        balance, src = live["balance"], f"实时读取 @ {live.get('ts')}"
    elif last and (last.get("after") or {}).get("balance") is not None:
        balance = last["after"]["balance"]
        src = "账本 · 最近运行 " + (last.get("ts") or "")[:16].replace("T", " ")
    elif hist and hist[-1].get("balance") is not None:
        balance, src = hist[-1]["balance"], "账本 · " + hist[-1]["date"]

    return {
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "today": today,
        "balance": balance,
        "balance_src": src,
        "today_stats": agg(today_runs),
        "search_target": int(CFG["search"]["count"]),
        "progress": progress,
        "live": live,
        "history": hist,
        "runs": [{k: r.get(k) for k in
                  ("ts", "date", "delta", "claimed", "claimed_extra",
                   "activities_done", "searches")}
                 for r in runs[-10:]],
        "system": {
            "watcher": watcher_running(),
            "bot_running": bot_running(),
            "edge_cdp": edge_cdp(),
            "tasks": task_info(),
        },
        "log_tail": tail,
    }


def do_live():
    if not _live_lock.acquire(blocking=False):
        return {"ok": False, "msg": "已有实时读取在进行"}
    try:
        if not edge_cdp():
            return {"ok": False, "msg": "Edge 专用实例未运行（等下一轮任务或先手动跑一次）"}
        from playwright.sync_api import sync_playwright
        from tasks import rewards
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(f"http://127.0.0.1:{EDGE_PORT}")
            ctx = b.contexts[0]
            fly = rewards.open_flyout(ctx)
            st = rewards.read_state(fly)
            fly.close()
        data = {
            "balance": st["balance"], "pending": st["pending"],
            "search": st["search"], "dailyset": st["dailyset"], "app": st["app"],
            "cards_undone": st["cards_undone"],
            "ts": datetime.now().strftime("%H:%M:%S"),
        }
        _live["ts"], _live["data"] = time.time(), data
        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:200]}
    finally:
        _live_lock.release()


def do_run():
    if bot_running():
        return {"ok": False, "msg": "已有一轮运行在进行中"}
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    subprocess.Popen([str(pyw), str(ROOT / "main.py")], cwd=str(ROOT), env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "msg": "已触发一轮运行（后台执行，约 1-3 分钟）"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (ROOT / "dashboard.html").read_text(encoding="utf-8")
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path.startswith("/api/state"):
            if "src=ext" in self.path and time.time() - _extseen["ts"] > 300:
                _extseen["ts"] = time.time()
                try:
                    with open(ROOT / "logs" / "dashboard.log", "a", encoding="utf-8") as f:
                        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                                f"[dashboard] extension client alive {self.path}\n")
                except Exception:
                    pass
            self._send(200, json.dumps(build_state(), ensure_ascii=False))
        elif self.path.startswith("/api/wallpaper"):
            self._send(200, json.dumps(get_wallpaper() or {}, ensure_ascii=False))
        elif self.path.startswith("/api/weather"):
            self._send(200, json.dumps(get_weather(), ensure_ascii=False))
        elif self.path.startswith("/api/quicklinks"):
            self._send(200, json.dumps(get_quicklinks(), ensure_ascii=False))
        elif self.path == "/favicon.ico":
            self._send(204, "")
        else:
            self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if self.path.startswith("/api/live"):
            self._send(200, json.dumps(do_live(), ensure_ascii=False))
        elif self.path.startswith("/api/run"):
            self._send(200, json.dumps(do_run(), ensure_ascii=False))
        else:
            self._send(404, '{"error":"not found"}')

    def log_message(self, *args):
        pass


def main():
    logf = ROOT / "logs" / "dashboard.log"

    def dlog(msg):
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        try:
            print(line, flush=True)
        except Exception:
            pass
        with open(logf, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        dlog(f"[dashboard] 启动失败（端口 {PORT} 被占用?）：{e}")
        raise
    dlog(f"[dashboard] serving http://127.0.0.1:{PORT}/")
    threading.Thread(target=task_refresher, daemon=True).start()  # 后台刷新缓存
    srv.serve_forever()


if __name__ == "__main__":
    main()
