# JD Sign - Windows 部署说明

## 环境要求
- Python 3.12+（已安装 Playwright）
- Google Chrome（`C:\Program Files\Google\Chrome\Application\chrome.exe`）
- PowerShell 5+

## 目录规划
```
{WORKSPACE}/
├── scripts/
│   ├── jd_chrome_daemon.ps1   ← Chrome 常驻脚本
│   ├── jd_sign_login_v2.py    ← 签到脚本
│   └── jd_keepalive_v2.py     ← 保活脚本
├── chrome-sign-profile/         ← Chrome Profile（含登录态）
├── jd_cookies.json             ← Cookie JSON 备份
├── jd_sign_v2.log             ← 签到日志
├── jd_keepalive_v2.log        ← 保活日志
└── jd_chrome_daemon.log       ← Chrome 启动日志
```

## 首次部署流程
1. 部署脚本到 `{WORKSPACE}/scripts/`
2. 有头模式启动 Chrome：`& "{SCRIPTS}/jd_chrome_daemon.ps1"`（不加 -headless）
3. 打开 `https://bean.jd.com` 扫码登录
4. 切换无头：`Stop-Process -Name chrome -Force; & "{SCRIPTS}/jd_chrome_daemon.ps1" -headless`
5. 验证：`{PYTHON} "{SCRIPTS}/jd_sign_login_v2.py" 9222`
