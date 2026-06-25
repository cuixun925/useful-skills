"""ksjsb_watch.py — 自动刷视频赚金币 (核心: 定时 swipe 翻下一个视频)

用法:
  python ksjsb_watch.py watch <minutes>     # 刷 N 分钟
  python ksjsb_watch.py like                # 双击点赞 (在视频页)
  python ksjsb_watch.py check [out.png]     # 截屏
  python ksjsb_watch.py swipe               # 单独翻一页

设计:
  - 视频自动播放 5-10s 后 swipe 翻下一个
  - 上滑 swipe: (540, 1500) -> (540, 400), 300ms
  - 偶尔双击屏幕中部点赞 (金币任务也会奖励点赞)
"""
import os
import subprocess
import sys
import time
import random
from pathlib import Path

ADB = os.environ.get("ADB", "adb")


def sh(*args, **kw):
    return subprocess.run([ADB, "shell", *args], capture_output=True, text=True, **kw).stdout


def tap(x, y):
    sh("input", "tap", str(int(x)), str(int(y)))


def swipe_up(ms=300):
    # 屏幕 1080x2285, 从中间下方滑到中间上方
    sh("input", "swipe", "540", "1500", "540", "400", str(int(ms)))


def double_tap(x=540, y=1100):
    tap(x, y)
    time.sleep(0.05)
    tap(x, y)


def screenshot(out):
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ADB, "exec-out", "screencap", "-p"], stdout=open(out, "wb"))


def watch_minutes(minutes: int, swipes_per_min: int = 7):
    """刷 N 分钟视频. swipes_per_min 控制翻页频率 (默认每 8.5s 翻一个)."""
    end = time.time() + minutes * 60
    n_swipe = 0
    n_like = 0
    print(f"[watch] 刷 {minutes} 分钟, 翻页频率 ~{swipes_per_min}/min")
    while time.time() < end:
        gap = 60 / swipes_per_min
        jitter = random.uniform(-0.4, 0.4) * gap
        time.sleep(max(2, gap + jitter))
        if random.random() < 0.2:
            double_tap(random.randint(450, 630), random.randint(800, 1400))
            n_like += 1
            time.sleep(0.3)
        swipe_up(300)
        n_swipe += 1
        if n_swipe % 5 == 0:
            remain = (end - time.time()) / 60
            print(f"[watch] swiped={n_swipe}  likes={n_like}  remain={remain:.1f}min")
    print(f"[watch] done. swiped={n_swipe} likes={n_like}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "watch"
    if cmd == "watch":
        minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 8
        watch_minutes(minutes)
    elif cmd == "check":
        out = sys.argv[2] if len(sys.argv) > 2 else "./ksjsb_check.png"
        screenshot(out)
        print(f"saved {out}")
    elif cmd == "swipe":
        swipe_up(300)
    elif cmd == "like":
        double_tap()
    else:
        print(f"unknown: {cmd}")
        sys.exit(1)
