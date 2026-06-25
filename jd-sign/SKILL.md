# JD Sign Skill - 京东自动签到 (v2)

## 环境适配

导入时根据目标机器替换占位符：

| 占位符 | 说明 |
|--------|------|
| `{WORKSPACE}` | 工作目录（脚本/日志/Cookie/Profile 都在其下） |
| `{SCRIPTS}` | 脚本目录（默认 `{WORKSPACE}/scripts`） |
| `{PYTHON}` | Python 命令（目标机器的 Python 路径） |

## 脚本说明

### jd_chrome_daemon.ps1 - Chrome 常驻

```powershell
# 无头启动
& "{SCRIPTS}/jd_chrome_daemon.ps1" -headless

# 有头启动（首次扫码用）
& "{SCRIPTS}/jd_chrome_daemon.ps1"

# 健康检查
& "{SCRIPTS}/jd_chrome_daemon.ps1" -check
```

- Profile：`{WORKSPACE}/chrome-sign-profile`
- CDP 端口：9222
- Chrome 已运行时直接退出，不重复启动

### jd_sign_login_v2.py - 执行签到

```python
{PYTHON} "{SCRIPTS}/jd_sign_login_v2.py" 9222
```

**流程：**
1. 检测 Chrome CDP（连不上 → 退出码 3）
2. 有 `thor` cookie → 直接用；无 → 从 `{WORKSPACE}/jd_cookies.json` 注入
3. 导航 `bean.jd.com/myJingBean/list`
4. 未登录 → 等扫码 90s（退出码 2）
5. 点击签到按钮 `#bean-sign-component .btn`
6. 验证日历节点含 `sign-in` / `continuity`
7. 保存 Cookie 到 `{WORKSPACE}/jd_cookies.json`
8. 失败自动重试 2 次（5s/15s 退避）

**退出码：** 0=成功 / 1=失败 / 2=需扫码 / 3=Chrome未运行 / 4=崩溃

### jd_keepalive_v2.py - Session 保活

```python
{PYTHON} "{SCRIPTS}/jd_keepalive_v2.py" 9222
```

**流程：**
1. 检测 Chrome CDP；不在 → 自动重启 daemon
2. 检查 `thor` cookie
3. 刷新 `bean.jd.com/myJingBean/list`
4. 保存 Cookie 到 `{WORKSPACE}/jd_cookies.json`
5. 验证页面含"我的京东"/"京豆"

**退出码：** 0=成功 / 1=失败 / 2=Chrome未运行 / 3=崩溃

---

## 故障排查

### 签到失败（退出码 1）
- 查看 `{WORKSPACE}/jd_sign_v2.log`
- 截图：`{WORKSPACE}/jd_sign_after.png`

### 需要扫码（退出码 2）
- 截图：`{WORKSPACE}/jd_qr_login.png`
- 用户扫码后 cookies 自动存入 Chrome profile

### Chrome 未运行（退出码 3）
- `jd_keepalive_v2.py` 会自动重启 daemon
- 手动启动：`& "{SCRIPTS}/jd_chrome_daemon.ps1" -headless`

### 脚本崩溃（退出码 4）
- 查看 `{WORKSPACE}/jd_sign_v2.log` 末尾 traceback

---

## 文件路径

| 文件 | 路径 |
|------|------|
| Chrome 启动脚本 | `{SCRIPTS}/jd_chrome_daemon.ps1` |
| 签到脚本 | `{SCRIPTS}/jd_sign_login_v2.py` |
| 保活脚本 | `{SCRIPTS}/jd_keepalive_v2.py` |
| Cookie 备份 | `{WORKSPACE}/jd_cookies.json` |
| Chrome Profile | `{WORKSPACE}/chrome-sign-profile` |
| 签到日志 | `{WORKSPACE}/jd_sign_v2.log` |
| 保活日志 | `{WORKSPACE}/jd_keepalive_v2.log` |

## 前置条件
- Chrome：`C:\Program Files\Google\Chrome\Application\chrome.exe`（或实际路径）
- Playwright 已安装
- 首次需用户扫码登录一次（建立 Chrome profile Session）
