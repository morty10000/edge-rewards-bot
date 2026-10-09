# 后台看守 — 你手动启动 Edge 时, 自动在后台触发一轮积分脚本(静默)
#
# 由计划任务 EdgeRewardsWatch (ONLOGON) 以 pythonw 启动(无窗口);
# 也可手动调试运行:  .venv\Scripts\python watch_edge.py
# 调试环境变量: WATCH_POLL_SEC / WATCH_DELAY_SEC / WATCH_DEBOUNCE_SEC
#               WATCH_DRY_RUN=1(只记录不触发) / WATCH_MAX_SEC=N(运行 N 秒后退出)

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil
import yaml

ROOT = Path(__file__).resolve().parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
W = CFG.get("watch", {})

POLL = int(os.environ.get("WATCH_POLL_SEC", W.get("poll_sec", 8)))
DEBOUNCE = int(os.environ.get("WATCH_DEBOUNCE_SEC", W.get("debounce_sec", 3 * 3600)))
DELAY = int(os.environ.get("WATCH_DELAY_SEC", W.get("delay_sec", 75)))
DRY = os.environ.get("WATCH_DRY_RUN") == "1"
MAX_SEC = float(os.environ.get("WATCH_MAX_SEC", 0))    # 0 = 永不退出

LOGF = ROOT / "logs" / "watch.log"
WSTATE = ROOT / "logs" / "watch_state.json"
RSTATE = ROOT / CFG.get("run", {}).get("state_file", "state.json")
LOGF.parent.mkdir(exist_ok=True)


def _effective_date():
    """奖励日：与 core.state.effective_date 保持一致的 30 分钟偏移"""
    try:
        sys.path.insert(0, str(ROOT))
        from core import state as state_mod
        return state_mod.effective_date()
    except Exception:
        from datetime import timedelta
        return (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d")


def load_last_trigger():
    try:
        return float(json.loads(WSTATE.read_text(encoding="utf-8")).get("last_trigger", 0))
    except Exception:
        return 0.0


def save_last_trigger(ts):
    try:
        WSTATE.write_text(json.dumps({"last_trigger": ts}), encoding="utf-8")
    except Exception:
        pass


def ran_today():
    """奖励日内是否已有一轮完成的记录（未被风控中止）；有则今天不再重复触发"""
    try:
        data = json.loads(RSTATE.read_text(encoding="utf-8"))
    except Exception:
        return False
    eff = _effective_date()
    for r in data.get("runs", []):
        if r.get("date") == eff and not r.get("blocked"):
            return True
    return False


def log(msg):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    with open(LOGF, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def main_edge_running():
    """主配置 Edge 是否在运行

    口径: msedge.exe 的"主进程"(命令行无 --type=) 且不属于脚本自己的
    .edge-profile 实例。默认 profile 启动时命令行不含 --user-data-dir,
    因此不能依赖路径标记，改用 主进程 + 排除法。
    """
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() != "msedge.exe":
                continue
            cl = " ".join(p.cmdline() or [])
            if "--type=" in cl:            # 只认浏览器主进程
                continue
            if ".edge-profile" in cl:      # 排除脚本专用实例
                continue
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def bot_running():
    for p in psutil.process_iter(["name"]):
        try:
            name = (p.info["name"] or "").lower()
            if "python" not in name:
                continue
            cl = " ".join(p.cmdline() or [])
            if "main.py" in cl:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def trigger():
    if DRY:
        log("[watch] DRY RUN: would trigger bot now")
        return
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pyw.exists():
        pyw = ROOT / ".venv" / "Scripts" / "python.exe"
    sink = open(LOGF, "a", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"      # 子进程输出统一 UTF-8，避免日志乱码
    subprocess.Popen([str(pyw), str(ROOT / "main.py")],
                     stdout=sink, stderr=sink, cwd=str(ROOT), env=env)
    log("[watch] bot launched (pythonw, background)")


def main():
    if not W.get("enabled", True):
        log("[watch] disabled in config.yaml (watch.enabled=false); exit")
        return 0
    # 单实例锁
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", 49517))
    except OSError:
        log("[watch] another watcher is already running; exit")
        return 0

    log(f"[watch] started  poll={POLL}s delay={DELAY}s debounce={DEBOUNCE}s dry={DRY}")
    t0 = time.time()
    last_trigger = load_last_trigger()
    armed = True                     # Edge 启动沿触发；同一次会话不重复

    while True:
        try:
            if MAX_SEC and time.time() - t0 > MAX_SEC:
                log("[watch] max-sec reached; exit")
                return 0
            if main_edge_running():
                now = time.time()
                if armed:
                    if bot_running():
                        log("[watch] edge detected; bot already running; skip")
                    elif ran_today():
                        log("[watch] edge detected; already ran today; skip")
                    elif (now - last_trigger) <= DEBOUNCE:
                        log(f"[watch] edge detected; debounce {int(now - last_trigger)}s <= {DEBOUNCE}s; skip")
                    else:
                        log(f"[watch] main Edge detected; waiting {DELAY}s before trigger")
                        time.sleep(DELAY)
                        if main_edge_running() and not bot_running() and not ran_today():
                            trigger()
                            last_trigger = time.time()
                            save_last_trigger(last_trigger)
                        else:
                            log("[watch] skipped (edge closed / bot running / already ran)")
                armed = False
            else:
                armed = True
            time.sleep(POLL)
        except KeyboardInterrupt:
            log("[watch] interrupted; exit")
            return 0
        except Exception as e:
            log(f"[watch] error: {str(e)[:150]}")
            time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main())
