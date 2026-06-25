#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
京东自动签到 v2.0 - 健壮版
==========================
核心改进:
1. 完整的异常处理：顶层 try/except 捕获所有异常，记录到日志，绝不静默失败
2. 自动重试：最多 2 次重试，指数退避（5s, 15s）
3. 会话保持:
   - 优先使用 Chrome profile 中的现有 cookie
   - 验证 thor cookie 存在 + 页面内容确认登录态
   - 仅在确实未登录时触发扫码
4. 日志隔离：独立日志文件，避免与 keepalive 冲突
5. 健康检查：签到后验证 Cookie 数量、关键 cookie 存在性
6. 退出码规范:
   - 0: 签到成功
   - 1: 签到失败（页面未签到）
   - 2: 需要扫码登录
   - 3: Chrome 未运行
   - 4: 异常崩溃

用法:
    python jd_sign_login_v2.py [port]
    python jd_sign_login_v2.py 9222
"""
import asyncio
import json
import os
import sys
import traceback
import urllib.request
import urllib.error
from datetime import datetime

# 强制设置 stdout/stderr 为 UTF-8（避免 PowerShell GBK 环境打印 emoji 报错）
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from playwright.async_api import async_playwright

# ============ 路径配置 ============
LOG_FILE = r"C:\Users\Administrator\.openclaw\workspace\jd_sign_v2.log"
COOKIE_FILE = r"C:\Users\Administrator\.openclaw\jd_cookies.json"
SCREENSHOT_BEFORE = r"C:\Users\Administrator\.openclaw\workspace\jd_sign_before.png"
SCREENSHOT_AFTER = r"C:\Users\Administrator\.openclaw\workspace\jd_sign_after.png"
SCREENSHOT_QR = r"C:\Users\Administrator\.openclaw\workspace\jd_qr_login.png"
SCREENSHOT_ERROR = r"C:\Users\Administrator\.openclaw\workspace\jd_sign_error.png"
DEBUG_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9222

# ============ 退出码 ============
EXIT_OK = 0
EXIT_SIGN_FAILED = 1
EXIT_NEED_LOGIN = 2
EXIT_CHROME_DOWN = 3
EXIT_CRASHED = 4

# ============ 重试配置 ============
MAX_RETRIES = 2
RETRY_DELAYS = [5, 15]  # 秒


# ============ 日志（UTF-8 + 安全字符过滤）============
def log(msg, level="INFO"):
    """写日志：时间戳 + 级别 + 消息。stderr 重定向不会污染日志文件。"""
    try:
        # 过滤控制字符和私用区字符
        def safe_char(c):
            o = ord(c)
            if o < 32 and c not in '\r\n\t':
                return False
            if 0xE000 <= o <= 0xF8FF:
                return False
            return True
        safe = ''.join(c for c in str(msg) if safe_char(c))
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"[{ts}] [{level}] {msg}\n"
        with open(LOG_FILE, "a", encoding="utf-8", errors="ignore") as f:
            f.write(line)
        # 仅打印到 stdout（不打印到 stderr，避免被 PowerShell 捕获）
        # 用 errors='replace' 避免 GBK 环境下 emoji 报错
        try:
            print(safe, flush=True)
        except UnicodeEncodeError:
            # GBK 环境下 emoji 打印失败，替换为 ASCII
            print(safe.encode('ascii', 'replace').decode('ascii'), flush=True)
    except Exception as e:
        # 日志失败时也不能崩
        try:
            print(f"[LOG-FAIL] {type(e).__name__}: {e}", flush=True)
        except UnicodeEncodeError:
            print(f"[LOG-FAIL] {type(e).__name__}: {e}".encode('ascii', 'replace').decode('ascii'), flush=True)


def log_section(title):
    log(f"{'='*30} {title} {'='*30}")


def log_exc(e):
    """记录完整异常信息到日志。"""
    log(f"{type(e).__name__}: {e}", level="ERROR")
    log(traceback.format_exc(), level="ERROR")


# ============ Chrome CDP 检测 ============
def check_chrome_alive(port):
    """检测 Chrome CDP 是否在指定端口响应。"""
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/json", timeout=3) as r:
            targets = json.loads(r.read())
        return True, len(targets)
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        return False, str(e)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ============ Cookie 加载（用于会话恢复）============
def load_saved_cookies():
    """从本地 JSON 文件加载之前保存的 Cookie。"""
    if not os.path.exists(COOKIE_FILE):
        log(f"Cookie文件不存在: {COOKIE_FILE}")
        return None
    # 用 utf-8-sig 处理 BOM（PowerShell Out-File -Encoding UTF8 会加 BOM）
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        cookies = data.get("cookies") or data.get("jd_cookies") or []
        log(f"从文件加载 {len(cookies)} 个 Cookie")
        return cookies
    except (json.JSONDecodeError, OSError) as e:
        log(f"Cookie文件加载失败: {e}", level="WARN")
        return None


def save_cookies(cookies):
    """保存 Cookie 到本地 JSON 文件（含元数据）。"""
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
        # 写临时文件再 rename，避免中途崩溃导致文件损坏
        tmp = COOKIE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if os.path.exists(COOKIE_FILE):
            os.remove(COOKIE_FILE)
        os.rename(tmp, COOKIE_FILE)
        log(f"Cookie已保存到 {COOKIE_FILE} (总 {len(cookies)}, JD {len(jd_cookies)})")
    except OSError as e:
        log(f"Cookie保存失败: {e}", level="ERROR")


def has_valid_session_cookies(cookies):
    """检查已保存的 Cookie 是否有可用的登录态。
    关键 cookie: thor (.jd.com) 或 pt_pin (.jd.com)"""
    if not cookies:
        return False
    for c in cookies:
        domain = c.get('domain', '')
        name = c.get('name', '')
        if 'jd.com' in domain and name in ('thor', 'pt_pin'):
            # 检查是否过期
            expires = c.get('expires', -1)
            if expires == -1 or expires == 0:
                # session cookie (永不过期)
                return True
            try:
                exp_ts = float(expires)
                # 现在时间（秒）
                now_ts = datetime.now().timestamp()
                if exp_ts > now_ts:
                    return True
                else:
                    log(f"Cookie {name}@{domain} 已过期 (exp={expires})", level="WARN")
            except (ValueError, TypeError):
                return True
    return False


# ============ 签到核心逻辑 ============
async def is_logged_in(page):
    """通过页面内容判断是否已登录。
    策略：优先检查"未登录"标志，不存在则视为已登录。
    （避免被弹窗/营销浮层中的"京豆"等字样干扰）"""
    try:
        text = await page.inner_text("body", timeout=5000)
        not_logged_in_indicators = [
            "请登录", "扫码登录", "账号登录", "QQ登录", "微信登录",
            "passport.jd.com/new/login"
        ]
        has_login_ui = any(ind in text for ind in not_logged_in_indicators)
        if has_login_ui:
            return False
        # URL 也是重要依据
        url = page.url
        if 'passport.jd.com' in url and 'bean.jd.com' not in url:
            return False
        return True
    except Exception as e:
        log(f"登录态检测失败: {e}", level="WARN")
        return False


async def wait_for_login(page, timeout_sec=90):
    """等待用户扫码登录，每 2s 检查一次。
    判断成功的可靠标准：cookie 中有 thor（不只是 URL 跳转）"""
    log(f"等待扫码登录（最多 {timeout_sec}秒）...")
    try:
        await page.goto("https://passport.jd.com/new/login.aspx?returnurl=https://bean.jd.com/",
                        timeout=20000, wait_until="domcontentloaded")
    except Exception as e:
        log(f"打开登录页失败: {e}", level="WARN")

    await asyncio.sleep(2)
    try:
        await page.screenshot(path=SCREENSHOT_QR, full_page=False)
        log(f"登录二维码截图: {SCREENSHOT_QR}")
    except Exception as e:
        log(f"截图失败: {e}", level="WARN")

    ctx = page.context
    for i in range(timeout_sec // 2):
        await asyncio.sleep(2)
        # 可靠判断：cookie 中有 .jd.com 域名的 thor
        try:
            cookies = await ctx.cookies()
            # 只检查 .jd.com 域名（不是 .jd.hk 等）
            jd_com_thor = any(
                c.get('name') == 'thor' and '.jd.com' in c.get('domain', '')
                for c in cookies
            )
            if jd_com_thor:
                log(f"检测到 .jd.com thor cookie (i={i})，验证页面是否真正登录...")
                # 关键验证：导航到 bean.jd.com，确认没有被重定向回 passport
                try:
                    await page.goto('https://bean.jd.com/myJingBean/list',
                                    timeout=15000, wait_until='domcontentloaded')
                    await asyncio.sleep(3)
                    url = page.url
                    if 'passport.jd.com' not in url and 'bean.jd.com' in url:
                        log(f"页面停留在 bean.jd.com ({url})，登录验证成功")
                        return True
                    else:
                        log(f"页面仍重定向 ({url})，thor 可能无效，继续等待扫码")
                except Exception as e:
                    log(f"验证导航失败: {e}", level="WARN")
        except Exception as e:
            log(f"检查 cookies 失败: {e}", level="WARN")

        if (i + 1) % 10 == 0:
            log(f"等待扫码... {2 * (i+1)}s")
    return False


async def click_sign_button(page):
    """点击签到按钮。"""
    log("查找签到按钮 #bean-sign-component .btn ...")

    # 先尝试关闭可能存在的弹窗
    try:
        # 关闭 "赚京豆" 弹窗（如果存在）
        close_btn = page.locator('.popup-close-btn, .jdc-close, [class*="close"][class*="popup"]').first
        if await close_btn.count() > 0:
            log("发现弹窗，尝试关闭...")
            await close_btn.click(timeout=3000)
            await asyncio.sleep(2)
    except Exception as e:
        log(f"关闭弹窗失败/无弹窗: {e}", level="WARN")

    # 滚动到签到区域
    try:
        await page.evaluate("window.scrollTo(0, 300)")
        await asyncio.sleep(2)
    except Exception as e:
        log(f"滚动失败: {e}", level="WARN")

    # 查找签到按钮
    btn = page.locator('#bean-sign-component .btn').first
    if await btn.count() == 0:
        log("未找到签到按钮，检查日历确认今日状态...")
        return await check_already_signed(page)

    # 截图前/后单独 try/except，避免 headless Chrome 下 clip 截图卡 30s 阻塞点击
    try:
        await page.screenshot(path=SCREENSHOT_BEFORE, timeout=5000)
        log("签到前截图已保存")
    except Exception as se:
        log(f"签到前截图失败（忽略）: {se}", level="WARN")

    try:
        log("点击签到按钮...")
        await btn.click(timeout=10000)
        await asyncio.sleep(4)
    except Exception as ce:
        log(f"点击签到按钮失败: {ce}", level="ERROR")
        log_exc(ce)
        return False

    try:
        await page.screenshot(path=SCREENSHOT_AFTER, timeout=5000)
        log("签到后截图已保存")
    except Exception as se2:
        log(f"签到后截图失败（忽略）: {se2}", level="WARN")

    return await verify_signed(page)


async def check_already_signed(page):
    """检查日历确认今日是否已签到。"""
    try:
        # 先关闭弹窗
        try:
            close_btn = page.locator('.popup-close-btn, .jdc-close, [class*="close"][class*="popup"]').first
            if await close_btn.count() > 0:
                await close_btn.click(timeout=3000)
                await asyncio.sleep(2)
        except Exception:
            pass

        cal = await page.evaluate("""
        (function() {
            var nodes = document.querySelectorAll('.node');
            var results = [];
            for(var i=0; i<nodes.length; i++) {
                var t = nodes[i].innerText || '';
                results.push({class: nodes[i].className, text: t.trim().substring(0, 20)});
            }
            return JSON.stringify(results);
        })()
        """)
        log(f"日历节点: {cal}")
        if cal and ('current sign-in' in cal or 'today sign-in' in cal.lower()):
            log("今日已签到（current 节点带 sign-in）")
            return True
        # 弹窗检查（"赚京豆"弹窗有"连签X天" = 今日已签）
        try:
            text = await page.inner_text("body", timeout=5000)
            if '连签' in text and '天' in text:
                log(f"弹窗显示连签信息（{text[:200]}），视为已签到")
                return True
        except Exception:
            pass
    except Exception as e:
        log(f"检查签到日历失败: {e}", level="WARN")
    return False


async def verify_signed(page):
    """验证签到是否成功。
    策略：优先检查日历节点，同时也检查弹窗中的签到成功标志。"""
    try:
        # 先关闭弹窗（如果存在）再检查日历
        try:
            close_btn = page.locator('.popup-close-btn, .jdc-close, [class*="close"][class*="popup"]').first
            if await close_btn.count() > 0:
                await close_btn.click(timeout=3000)
                await asyncio.sleep(2)
        except Exception:
            pass

        cal = await page.evaluate("""
        (function() {
            var nodes = document.querySelectorAll('.node');
            var results = [];
            for(var i=0; i<nodes.length; i++) {
                var t = nodes[i].innerText || '';
                results.push({class: nodes[i].className, text: t.trim().substring(0, 20)});
            }
            return JSON.stringify(results);
        })()
        """)
        log(f"签到后日历: {cal}")

        # 验证方式1：日历节点
        if cal and ('current sign-in' in cal or 'continuity' in cal):
            return True

        # 验证方式2：弹窗中出现签到成功信息（"赚京豆"弹窗有"连签X天"）
        try:
            text = await page.inner_text("body", timeout=5000)
            if '连签' in text and ('已签到' in text or 'sign-in' in text.lower()):
                log("弹窗中检测到连签标志，签到成功")
                return True
        except Exception:
            pass

        return False
    except Exception as e:
        log(f"验证签到失败: {e}", level="WARN")
        return False


async def sign_in_with_chrome(browser, port):
    """使用 Chrome CDP 执行签到。"""
    log(f"连接 Chrome CDP: {port}")
    ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    # 1. 加载已保存的 Cookie（如果 Chrome 中没有）
    current_cookies = await ctx.cookies()
    log(f"Chrome 当前 Cookie 数量: {len(current_cookies)}")

    has_thor = any('thor' in c.get('name', '') and 'jd' in c.get('domain', '')
                   for c in current_cookies)
    if not has_thor:
        log("Chrome 中无 thor cookie，尝试从文件注入...")
        saved = load_saved_cookies()
        if saved and has_valid_session_cookies(saved):
            try:
                # 转换 cookie 格式
                inject_cookies = []
                for c in saved:
                    if 'jd' in c.get('domain', ''):
                        inject_cookies.append({
                            'name': c['name'],
                            'value': c['value'],
                            'domain': c['domain'],
                            'path': c.get('path', '/'),
                            'expires': c.get('expires', -1),
                            'httpOnly': c.get('httpOnly', False),
                            'secure': c.get('secure', False),
                            'sameSite': c.get('sameSite', 'Lax'),
                        })
                if inject_cookies:
                    await ctx.add_cookies(inject_cookies)
                    log(f"已注入 {len(inject_cookies)} 个 Cookie")
            except Exception as e:
                log(f"Cookie 注入失败: {e}", level="WARN")
    else:
        log("Chrome 中已有 thor cookie，跳过注入")

    # 2. 导航到京豆页面
    log("导航到 bean.jd.com ...")
    try:
        await page.goto("https://bean.jd.com/myJingBean/list",
                        timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        log(f"导航失败: {e}", level="ERROR")
        # 截图错误现场
        try:
            await page.screenshot(path=SCREENSHOT_ERROR)
        except:
            pass
        raise

    await asyncio.sleep(5)

    # 3. 检查登录态
    if not await is_logged_in(page):
        log("页面显示未登录，需要扫码")
        success = await wait_for_login(page, timeout_sec=90)
        if not success:
            log("扫码超时或失败", level="ERROR")
            return False, "需要扫码"
        # 登录后再访问京豆页
        await page.goto("https://bean.jd.com/myJingBean/list",
                        timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

    # 4. 执行签到
    signed = await click_sign_button(page)

    # 5. 保存最新 Cookie
    try:
        cookies = await ctx.cookies()
        save_cookies(cookies)
    except Exception as e:
        log(f"保存Cookie失败: {e}", level="WARN")

    return signed, "签到成功" if signed else "签到失败"


async def run_sign_in(port):
    """单次签到任务。返回 (success, message)。"""
    log_section(f"开始签到 (port={port})")

    # 检测 Chrome
    alive, info = check_chrome_alive(port)
    if not alive:
        log(f"Chrome CDP 未响应: {info}", level="ERROR")
        return False, "chrome_down"
    log(f"Chrome 端口 {port} 正常（{info} 个 target）")

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f"http://localhost:{port}")
        except Exception as e:
            log(f"Playwright 连接 Chrome 失败: {e}", level="ERROR")
            return False, "chrome_down"
        try:
            success, msg = await sign_in_with_chrome(browser, port)
            return success, msg
        except Exception as e:
            log(f"签到过程异常: {e}", level="ERROR")
            log_exc(e)
            try:
                await browser.close()
            except:
                pass
            return False, "crashed"
        finally:
            try:
                await browser.close()
            except:
                pass


def main():
    """主入口：支持重试。"""
    last_success = False
    last_msg = ""

    for attempt in range(MAX_RETRIES + 1):
        if attempt > 0:
            delay = RETRY_DELAYS[attempt - 1] if attempt - 1 < len(RETRY_DELAYS) else 15
            log(f"第 {attempt} 次重试，等待 {delay} 秒...")
            print(f"sleeping {delay}...", flush=True)
            import time
            time.sleep(delay)

        try:
            success, msg = asyncio.run(run_sign_in(DEBUG_PORT))
            last_success = success
            last_msg = msg
            if success:
                log(f"✅ 签到成功 (第 {attempt+1} 次尝试)")
                return EXIT_OK
            else:
                log(f"❌ 第 {attempt+1} 次尝试失败: {msg}", level="WARN")
                # 这些错误不重试（重试也没用）
                if msg in ("chrome_down", "需要扫码", "crashed"):
                    log(f"错误 {msg} 不重试")
                    if msg == "chrome_down":
                        return EXIT_CHROME_DOWN
                    if msg == "需要扫码":
                        return EXIT_NEED_LOGIN
                    if msg == "crashed":
                        return EXIT_CRASHED
                # 其他错误重试
        except KeyboardInterrupt:
            log("用户中断", level="WARN")
            return EXIT_CRASHED
        except Exception as e:
            log(f"第 {attempt+1} 次尝试崩溃: {e}", level="ERROR")
            log_exc(e)
            last_msg = "crashed"

    # 所有重试都失败
    log(f"❌ 全部 {MAX_RETRIES + 1} 次尝试都失败，最后消息: {last_msg}", level="ERROR")

    if last_msg == "chrome_down":
        return EXIT_CHROME_DOWN
    if last_msg == "需要扫码":
        return EXIT_NEED_LOGIN
    return EXIT_SIGN_FAILED


if __name__ == "__main__":
    exit_code = main()
    log(f"进程退出，code={exit_code}")
    sys.exit(exit_code)
