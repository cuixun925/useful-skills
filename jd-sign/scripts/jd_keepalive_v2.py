#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
京东 Session 保活 v2.0 - 健壮版
==============================
核心改进:
1. 完整异常处理：所有异常都记录到日志
2. Chrome 健康检查：如果 Chrome 挂了，调用 daemon 脚本重启
3. 会话验证：检测 thor cookie 是否存在
4. 日志隔离：独立日志文件
5. 静默运行：保活任务一般无错误，错误时正常退出码非 0

退出码:
  0: 保活成功
  1: 保活失败（但 Chrome 在）
  2: Chrome 未运行（已尝试重启）
  3: 崩溃
"""
import asyncio
import json
import os
import sys
import traceback
import urllib.request
import urllib.error
from datetime import datetime

# 强制设置 stdout/stderr 为 UTF-8
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from playwright.async_api import async_playwright

# ============ 路径配置 ============
LOG_FILE = r"C:\Users\Administrator\.openclaw\workspace\jd_keepalive_v2.log"
COOKIE_FILE = r"C:\Users\Administrator\.openclaw\jd_cookies.json"
DAEMON_SCRIPT = r"C:\Users\Administrator\.openclaw\scripts\jd_chrome_daemon.ps1"
DEBUG_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9222

# ============ 退出码 ============
EXIT_OK = 0
EXIT_KEEPALIVE_FAILED = 1
EXIT_CHROME_DOWN = 2
EXIT_CRASHED = 3

# ============ 内部工具 ============
def log(msg, level="INFO"):
    try:
        def safe_char(c):
            o = ord(c)
            if o < 32 and c not in '\r\n\t':
                return False
            if 0xE000 <= o <= 0xF8FF:
                return False
            return True
        safe = ''.join(c for c in str(msg) if safe_char(c))
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(LOG_FILE, "a", encoding="utf-8", errors="ignore") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")
        # 打印到 stdout（用 errors='replace' 避免 GBK 环境 emoji 报错）
        try:
            print(safe, flush=True)
        except UnicodeEncodeError:
            print(safe.encode('ascii', 'replace').decode('ascii'), flush=True)
    except Exception as e:
        try:
            print(f"[LOG-FAIL] {type(e).__name__}: {e}", flush=True)
        except UnicodeEncodeError:
            print(f"[LOG-FAIL] {type(e).__name__}: {e}".encode('ascii', 'replace').decode('ascii'), flush=True)


def log_exc(e):
    log(f"{type(e).__name__}: {e}", level="ERROR")
    log(traceback.format_exc(), level="ERROR")


def check_chrome_alive(port):
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/json", timeout=3) as r:
            targets = json.loads(r.read())
        return True, len(targets)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def try_restart_chrome():
    """尝试通过 daemon 脚本重启 Chrome。"""
    log("尝试重启 Chrome ...")
    try:
        import subprocess
        # 用 PowerShell 跑 daemon 脚本（headless 模式）
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", DAEMON_SCRIPT, "-headless"],
            capture_output=True, text=True, timeout=60
        )
        log(f"daemon exit code: {result.returncode}")
        if result.stdout:
            log(f"daemon stdout: {result.stdout[:500]}")
        if result.stderr:
            log(f"daemon stderr: {result.stderr[:500]}", level="WARN")
        # 等待 5 秒
        import time
        time.sleep(5)
        alive, info = check_chrome_alive(DEBUG_PORT)
        log(f"重启后 Chrome 状态: {alive} ({info})")
        return alive
    except Exception as e:
        log(f"重启 Chrome 失败: {e}", level="ERROR")
        log_exc(e)
        return False


def save_cookies(cookies):
    """保存 Cookie 到本地 JSON 文件。"""
    try:
        jd_cookies = [c for c in cookies if
                      'jd.com' in c.get('domain', '') or
                      'jd.hk' in c.get('domain', '') or
                      'jingdong' in c.get('domain', '')]
        data = {
            "saved_at": datetime.now().isoformat(),
            "total": len(cookies),
            "jd_total": len(jd_cookies),
            "cookies": cookies,
            "jd_cookies": jd_cookies,
        }
        tmp = COOKIE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if os.path.exists(COOKIE_FILE):
            os.remove(COOKIE_FILE)
        os.rename(tmp, COOKIE_FILE)
        log(f"Cookie已保存 (总 {len(cookies)}, JD {len(jd_cookies)})")
    except OSError as e:
        log(f"Cookie保存失败: {e}", level="ERROR")


async def keepalive_session(port):
    """单次保活任务。"""
    log(f"===== 保活开始 (port={port}) =====")
    alive, info = check_chrome_alive(port)
    if not alive:
        log(f"Chrome 未运行: {info}", level="WARN")
        # 尝试重启
        if not try_restart_chrome():
            return False, "chrome_down"
    else:
        log(f"Chrome 运行中 ({info} 个 target)")

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f"http://localhost:{port}")
        except Exception as e:
            log(f"连接 Chrome 失败: {e}", level="ERROR")
            return False, "chrome_down"
        try:
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            # 检查当前 cookies
            cookies = await ctx.cookies()
            names = [c['name'] for c in cookies]
            has_thor = 'thor' in names
            log(f"Cookie 数量: {len(cookies)}, thor: {'有' if has_thor else '无'}")

            # 刷新京豆页面
            log("刷新京豆页面...")
            try:
                await page.goto("https://bean.jd.com/myJingBean/list",
                                timeout=20000, wait_until="domcontentloaded")
                await asyncio.sleep(5)
            except Exception as e:
                log(f"导航失败: {e}", level="WARN")
                # 即使导航失败，cookies 可能还是有效的

            # 重新获取 cookies（页面加载后可能更新）
            cookies = await ctx.cookies()
            save_cookies(cookies)

            # 验证登录态
            try:
                text = await page.inner_text("body", timeout=5000)
                if '我的京东' in text or '京豆' in text:
                    log("登录态正常")
                else:
                    log("登录态未知（页面无明确标志）", level="WARN")
            except Exception as e:
                log(f"验证登录态失败: {e}", level="WARN")

            log("===== 保活完成 =====")
            return True, "ok"
        except Exception as e:
            log(f"保活过程异常: {e}", level="ERROR")
            log_exc(e)
            return False, "crashed"
        finally:
            try:
                await browser.close()
            except:
                pass


def main():
    try:
        success, msg = asyncio.run(keepalive_session(DEBUG_PORT))
        if success:
            return EXIT_OK
        if msg == "chrome_down":
            return EXIT_CHROME_DOWN
        if msg == "crashed":
            return EXIT_CRASHED
        return EXIT_KEEPALIVE_FAILED
    except KeyboardInterrupt:
        log("用户中断", level="WARN")
        return EXIT_CRASHED
    except Exception as e:
        log(f"保活主函数异常: {e}", level="ERROR")
        log_exc(e)
        return EXIT_CRASHED


if __name__ == "__main__":
    exit_code = main()
    log(f"进程退出，code={exit_code}")
    sys.exit(exit_code)
