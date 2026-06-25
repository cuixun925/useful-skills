"""
ksjsb_loop.py — 持续循环跑金币（适合 cron / 任务计划程序）

每轮执行：
1. 检测设备状态
2. 强保活回任务中心
3. 跑一遍 run-all 流程
4. 写日志 + 通知
5. 等待 5 分钟或 10 分钟（宝箱冷却时间）
6. 继续下一轮

用法：
  python ksjsb_loop.py              # 默认循环
  python ksjsb_loop.py --interval 5 # 轮间隔 5 分钟
  python ksjsb_loop.py --max 5      # 最多跑 5 轮后退出（调试用）
"""
import os
import sys
import time
import argparse
import subprocess
import logging
from datetime import datetime
from pathlib import Path

# 复用 ksjsb_auto 的核心逻辑
sys.path.insert(0, str(Path(__file__).parent))
import ksjsb_auto as auto

# 配置
LOG_DIR = Path(os.environ.get("KSJSB_LOG_DIR", auto.WORKSPACE))
LOG_FILE = LOG_DIR / "ksjsb_loop.log"

# 初始化日志
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("ksjsb_loop")


def device_online():
    """检查设备是否在线且未 unauthorized"""
    r = subprocess.run([auto.ADB, "devices"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if auto.PKG.split(".")[2] in line:  # 简单匹配 nebula
            continue
        if "device" in line and "unauthorized" not in line and "offline" not in line:
            # 检查是不是真的连接
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                return True
    # 简化版：直接 grep b74e27d8
    r2 = subprocess.run([auto.ADB, "devices"], capture_output=True, text=True)
    return "b74e27d8\tdevice" in r2.stdout or "*\tdevice" in r2.stdout


def run_one_round(round_no):
    """跑一轮完整流程"""
    log.info(f"========== Round {round_no} ==========")
    
    # 1. 设备检查
    if not device_online():
        log.warning("设备掉线，等待恢复...")
        return {"status": "device_offline", "coins": 0}
    
    # 2. 强保活
    try:
        auto.ensure_in_task_center()
    except Exception as e:
        log.exception("ensure_in_task_center 失败")
        return {"status": "ensure_failed", "coins": 0}
    
    # 3. 读取跑前金币
    before = auto.read_jinbi() if hasattr(auto, "read_jinbi") else None
    
    # 4. 跑任务
    try:
        auto.run_all()
    except Exception as e:
        log.exception("run_all 失败")
        return {"status": "run_failed", "coins": 0, "before": before}
    
    # 5. 读取跑后金币
    after = auto.read_jinbi() if hasattr(auto, "read_jinbi") else None
    delta = (after or 0) - (before or 0) if (after and before) else None
    
    log.info(f"本轮结束: 跑前={before}, 跑后={after}, 增量={delta}")
    return {"status": "ok", "before": before, "after": after, "delta": delta}


def main():
    parser = argparse.ArgumentParser(description="ksjsb 持续循环跑金币")
    parser.add_argument("--interval", type=int, default=10,
                        help="每轮间隔分钟（默认 10）")
    parser.add_argument("--max", type=int, default=0,
                        help="最多跑 N 轮后退出（默认 0 = 无限）")
    args = parser.parse_args()
    
    log.info(f"========== KSJSB LOOP START ==========")
    log.info(f"interval={args.interval}min, max_rounds={args.max or '∞'}")
    log.info(f"log file: {LOG_FILE}")
    
    round_no = 0
    consecutive_zero = 0  # 连续 0 增长轮数
    try:
        while True:
            round_no += 1
            result = run_one_round(round_no)
            
            # 检查结果
            if result["status"] == "device_offline":
                log.warning("设备掉线，60s 后重试...")
                time.sleep(60)
                continue
            
            if result["status"] == "ok":
                delta = result.get("delta")
                if delta is None:
                    log.info("无法读金币数，按正常处理")
                    consecutive_zero = 0
                elif delta <= 0:
                    consecutive_zero += 1
                    log.info(f"本轮金币无增长 (连续 {consecutive_zero})")
                    if consecutive_zero >= 3:
                        log.info("连续 3 轮无增长，任务可能已做完，进入长间隔等待")
                        time.sleep(args.interval * 60)
                        consecutive_zero = 0
                else:
                    consecutive_zero = 0
                    log.info(f"🎉 本轮 +{delta} 金币!")
            
            # 退出条件
            if args.max and round_no >= args.max:
                log.info(f"达到 max={args.max} 轮，退出")
                break
            
            # 等待下一轮
            log.info(f"等待 {args.interval} 分钟后开始下一轮...")
            time.sleep(args.interval * 60)
    
    except KeyboardInterrupt:
        log.info("用户中断 (Ctrl+C)")
    except Exception as e:
        log.exception("主循环异常")
    finally:
        log.info(f"========== KSJSB LOOP END (共 {round_no} 轮) ==========")


if __name__ == "__main__":
    main()
