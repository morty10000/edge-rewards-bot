"""运行状态存储（幂等支持）"""

import json
from datetime import datetime, timedelta
from pathlib import Path


def today():
    return datetime.now().strftime("%Y-%m-%d")


def effective_date(minutes=30):
    """奖励日偏移：每日重置约 23:40，向后平移 30 分钟避免记账错位"""
    return (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d")


def load(path):
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(path, state):
    Path(path).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def record_run(path, summary):
    state = load(path)
    state.setdefault("runs", []).append(summary)
    state["runs"] = state["runs"][-60:]          # 只留最近 60 次
    state["last_summary"] = summary
    save(path, state)
    return state
