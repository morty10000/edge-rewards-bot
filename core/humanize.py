"""拟人化：随机间隔 / 随机停留 / 模拟输入"""

import random
import time


def gap(cfg_range, log=None, tag=""):
    lo, hi = cfg_range
    t = random.uniform(lo, hi)
    if log and tag:
        log(f"[humanize] {tag} wait {t:.1f}s")
    time.sleep(t)
    return t


def dwell(cfg_range):
    lo, hi = cfg_range
    time.sleep(random.uniform(lo, hi))


def type_delay():
    return random.randint(60, 140)


def wheel_amount():
    return random.randint(300, 900)
