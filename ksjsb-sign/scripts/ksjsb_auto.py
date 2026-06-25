"""
ksjsb_auto.py — 快手极速版任务中心全自动做任务脚本
设计：1080x2285 (UI bounds) / 1080x2400 (display)
所有点击用 swipe 1px 代替 tap，确保 WebView 元素能响应
"""
import os
import subprocess
import time
import sys
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# ADB 路径 - 自动检测
ADB = os.environ.get("ADB", "adb")  # 默认用 PATH 里的 adb
# 工作目录 - 所有截图/UI dump 存这里
WORKSPACE = os.environ.get("KSJSB_WORKSPACE", os.getcwd())
# 包名
PKG = "com.kuaishou.nebula"
TASK_ACTIVITY = f"{PKG}/com.yxcorp.gifshow.HomeActivity"

SCREEN_W = 1080
SCREEN_UI_H = 2285  # UI dump reported bounds max y


def sh(*args):
    return subprocess.run([ADB, "shell", *args], capture_output=True, text=True).stdout.strip()


def screencap(out=None):
    if not out:
        ts = time.strftime("%H%M%S")
        out = Path(WORKSPACE) / f"ks_{ts}.png"
    subprocess.run([ADB, "exec-out", "screencap", "-p"], stdout=open(str(out), "wb"))
    return str(out)


def ui_dump(out=None):
    if not out:
        ts = time.strftime("%H%M%S")
        out = Path(WORKSPACE) / f"ks_ui_{ts}.xml"
    sh("uiautomator", "dump", "/sdcard/ui.xml")
    subprocess.run([ADB, "pull", "/sdcard/ui.xml", str(out)], capture_output=True)
    return str(out)


def parse_bounds(s):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", s)
    if not m:
        return None
    return tuple(map(int, m.groups()))


def swipe_tap(x, y, ms=50):
    """极短距 swipe = 模拟精准 tap，比 input tap 更可靠"""
    x2, y2 = int(x) + 1, int(y) + 1
    sh("input", "swipe", str(int(x)), str(int(y)), str(x2), str(y2), str(ms))
    time.sleep(0.3)


def tap(x, y):
    sh("input", "tap", str(int(x)), str(int(y)))
    time.sleep(0.3)


def back(n=1):
    for _ in range(n):
        sh("input", "keyevent", "KEYCODE_BACK")
        time.sleep(0.8)


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_screen_info():
    """获取当前屏幕信息"""
    info = {}
    r = subprocess.run([ADB, "shell", "dumpsys", "window"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if "mCurrentFocus" in line:
            info["focus"] = line.strip()
    return info


def find_node_text(xml_path, text_substr, below_y=0):
    """在 UI dump 中找包含文字的节点，返回中心坐标"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    for n in root.iter("node"):
        t = n.get("text", "").strip()
        if text_substr not in t:
            continue
        b = n.get("bounds", "")
        if not b or b == "[0,0][0,0]":
            continue
        bn = parse_bounds(b)
        if not bn:
            continue
        cx = (bn[0] + bn[2]) // 2
        cy = (bn[1] + bn[3]) // 2
        if cy < below_y:
            continue
        log(f"  found '{t}' at ({cx},{cy}) bounds={b}")
        return cx, cy, t
    return None, None, None


def find_clickable_by_text(xml_path, text_substr, below_y=0):
    """找可点击的节点"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    for n in root.iter("node"):
        if n.get("clickable") != "true":
            continue
        t = n.get("text", "").strip()
        if text_substr not in t:
            continue
        b = n.get("bounds", "")
        if not b or b == "[0,0][0,0]":
            continue
        bn = parse_bounds(b)
        if not bn:
            continue
        if bn[1] < below_y:
            continue
        cx = (bn[0] + bn[2]) // 2
        cy = (bn[1] + bn[3]) // 2
        log(f"  clickable '{t}' at ({cx},{cy})")
        return cx, cy, t
    return None, None, None


def goto_task_center():
    """确保在任务中心"""
    log("ensure in task center...")
    info = get_screen_info()
    log(f"  current focus: {info.get('focus','')}")
    if "HomeActivity" not in info.get("focus", ""):
        log("  not HomeActivity, pressing back")
        back(3)
    # 点底部去赚钱 tab
    swipe_tap(756, 2269)
    time.sleep(2)
    log("  tapped 去赚钱 tab")
    return True


def close_popups(max_attempts=5):
    """关闭所有弹窗，返回关闭次数"""
    closed = 0
    for i in range(max_attempts):
        time.sleep(1)
        subprocess.run([ADB, "shell", "input", "keyevent", "KEYCODE_BACK"], capture_output=True)
        time.sleep(0.5)
        subprocess.run([ADB, "shell", "input", "keyevent", "KEYCODE_BACK"], capture_output=True)
        time.sleep(0.5)
        xml = ui_dump()
        try:
            for n in ET.parse(xml).iter("node"):
                t = n.get("text", "").strip()
                if any(kw in t for kw in ["瓜分", "立即参与", "立即签到", "奖励", "好礼"]):
                    log(f"  popup still there: {t[:20]}")
                    closed += 1
                    continue
        except ET.ParseError:
            pass
        break
    return closed


def ensure_in_task_center():
    """强保活：遇到任何异常情况都强制回到任务中心"""
    info = get_screen_info()
    focus = info.get("focus", "")
    log(f"  [focus] {focus}")
    if "AwardVideoPlayActivity" in focus:
        for _ in range(6):
            sh("input", "keyevent", "KEYCODE_BACK")
            time.sleep(0.5)
        time.sleep(2)
    if "NotificationShade" in get_screen_info().get("focus", ""):
        sh("service", "call", "statusbar", "1")
        time.sleep(1)
    if "com.heytap.market" in get_screen_info().get("focus", ""):
        sh("am", "force-stop", "com.heytap.market")
        time.sleep(1)
    sh("am", "force-stop", PKG)
    time.sleep(1)
    sh("monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(6)
    swipe_tap(756, 2269)
    time.sleep(3)


def do_signin():
    """做签到任务"""
    log("=== SIGNIN ===")
    xml = ui_dump()
    cx, cy, t = find_node_text(xml, "立即签到")
    if not cx:
        log("  already signed (no 立即签到 found)")
        for n in ET.parse(xml).iter("node"):
            t2 = n.get("text", "").strip()
            if "签到" in t2:
                log(f"  signin node: {t2!r}")
        return False
    log(f"  tapping 立即签到 at ({cx},{cy})")
    swipe_tap(cx, cy)
    time.sleep(3)
    close_popups(3)
    xml2 = ui_dump()
    cx2, cy2, t2 = find_node_text(xml2, "去看视频")
    if cx2:
        log(f"  found '去看视频' at ({cx2},{cy2}), tapping")
        swipe_tap(cx2, cy2)
        time.sleep(5)
        watch_videos(minutes=5)
        back(2)
    return True


def watch_videos(minutes=5):
    """在首页刷视频（每8秒翻一个）"""
    log(f"=== WATCH {minutes} MIN ===")
    end = time.time() + minutes * 60
    n = 0
    while time.time() < end:
        time.sleep(7 + (n % 3))  # 7-9秒
        # 上滑翻下一个
        sh("input", "swipe", "540", "1500", "540", "400", "300")
        n += 1
        if n % 10 == 0:
            remain = (end - time.time()) / 60
            log(f"  swiped {n} times, remain {remain:.1f}min")
    log(f"  watch done, {n} swipes")


def do_claim_reward():
    """领取待奖励金 + 宝箱"""
    log("=== CLAIM REWARDS ===")
    xml = ui_dump()
    cx, cy, t = find_node_text(xml, "待领")
    if cx:
        log(f"  claiming '待领' at ({cx},{cy})")
        swipe_tap(cx, cy)
        time.sleep(2)
    cx2, cy2, t2 = find_node_text(xml, "点可领")
    if cx2:
        log(f"  claiming '点可领' at ({cx2},{cy2})")
        swipe_tap(cx2, cy2)
        time.sleep(2)
    close_popups(2)


def do_short_tasks():
    """做短时任务（广告+视频）"""
    log("=== SHORT TASKS ===")
    goto_task_center()
    time.sleep(1)
    xml = ui_dump()
    cx, cy, t = find_clickable_by_text(xml, "领福利")
    if cx:
        log(f"  doing 看广告 task at ({cx},{cy})")
        swipe_tap(cx, cy)
        time.sleep(10)
        back(2)
        time.sleep(1)
    goto_task_center()
    xml2 = ui_dump()
    cx2, cy2, t2 = find_clickable_by_text(xml2, "去观看")
    if cx2:
        log(f"  doing 看视频 task at ({cx2},{cy2})")
        swipe_tap(cx2, cy2)
        time.sleep(2)
        info = get_screen_info()
        if "LiveSlide" in info.get("focus", ""):
            log("  jumped to live room, back out")
            back(2)
        else:
            watch_videos(minutes=5)
            back(2)


def run_all():
    """一键执行所有任务"""
    log("========== KSJSB AUTO START ==========")
    screencap()

    # 强保活回到任务中心
    ensure_in_task_center()
    time.sleep(2)

    # 1. 签到
    do_signin()
    time.sleep(2)

    # 2. 领待奖励金
    ensure_in_task_center()
    do_claim_reward()
    time.sleep(2)

    # 3. 短任务（广告+视频）
    ensure_in_task_center()
    do_short_tasks()

    # 4. 再刷一轮视频
    log("=== EXTRA VIDEO FEED ===")
    back(2)
    time.sleep(2)
    watch_videos(minutes=3)

    log("========== DONE ==========")
    screencap()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run-all"
    if cmd == "scan":
        goto_task_center()
        time.sleep(2)
        xml = ui_dump()
        print("=== ALL TEXT NODES ===")
        for n in ET.parse(xml).iter("node"):
            t = n.get("text", "").strip()
            b = n.get("bounds", "")
            if t and b and b != "[0,0][0,0]":
                print(f"  {b:30s} {t!r}")
    elif cmd == "claim":
        goto_task_center()
        time.sleep(2)
        do_claim_reward()
    elif cmd == "signin":
        goto_task_center()
        time.sleep(2)
        do_signin()
    elif cmd == "watch":
        mins = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        watch_videos(mins)
    elif cmd == "short":
        do_short_tasks()
    elif cmd == "run-all":
        run_all()
