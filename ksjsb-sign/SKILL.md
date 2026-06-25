---
name: ksjsb-sign
description: 快手极速版自动赚金币 Skill - 通过 ADB 控制安卓手机自动完成快手极速版"去赚钱"任务中心的签到/领金币/看广告/刷视频/开宝箱任务。当用户说"快手极速版赚金币"、"快手去赚钱任务"、"ksjsb auto"、"快手自动签到"、"快手刷视频赚金币"、或要求自动化操作快手极速版时使用。设备通过 USB 调试连接电脑，脚本支持一键跑全流程（签到→领金币→开宝箱→刷视频），不需要 root。**不要 undertrigger** - 用户说"快手签到"、"快手刷金币"、"快手极速版任务"都应该触发本 Skill。
---

# ksjsb-sign — 快手极速版自动赚金币

通过 ADB 控制安卓手机（USB 调试模式），自动完成快手极速版任务中心（去赚钱频道）的所有任务赚取金币。

## 触发场景

- 用户连接手机后说"做快手任务"、"赚金币"、"跑一下快手"
- 用户问"快手极速版怎么自动签到"、"怎么自动刷视频"
- 用户要求优化 ksjsb 自动化脚本

## 适用设备

- 安卓手机（测试机型：OPPO PEGM00 / Realme X2 Pro，ColorOS）
- 屏幕分辨率：1080×2285（UI）/ 1080×2400（display）
- 快手极速版包名：`com.kuaishou.nebula`
- 任务中心 Activity：`com.kuaishou.nebula/com.yxcorp.gifshow.HomeActivity`

## 环境准备

### 1. ADB

```bash
# Windows: C:\platform-tools\adb.exe
# Mac/Linux: adb (PATH)
adb devices  # 确认设备已连接
```

### 2. 手机开启 USB 调试

- 设置 → 关于手机 → 连续点击"版本号" 7 次激活开发者选项
- 开发者选项 → 打开"USB 调试"
- 首次连接在手机上点"允许 USB 调试"

### 3. Python 依赖

```bash
pip install uiautomator2 adbutils apkutils2
```

（大部分 ADB 自动化只需要 `subprocess`，`uiautomator2` 是可选的 UI dump 工具）

## 核心脚本

### `scripts/ksjsb_auto.py` — 主自动化

```bash
# 一键做所有任务
python scripts/ksjsb_auto.py run-all

# 单独操作
python scripts/ksjsb_auto.py scan          # 扫描当前页面任务
python scripts/ksjsb_auto.py signin        # 签到
python scripts/ksjsb_auto.py claim          # 领取待奖励金 + 宝箱
python scripts/ksjsb_auto.py short          # 看广告 + 刷视频
python scripts/ksjsb_auto.py watch <分钟>   # 单纯刷视频 N 分钟
```

**完整流程（run-all）：**
1. 启动快手极速版 → 进"去赚钱"任务中心
2. 签到（每日一次，奖励 ~9888+ 金币）
3. 领待奖励金（"待领 X 金币立即领取"）
4. 开宝箱（"点可领 X 金币"看广告 25s 领奖励）
5. 看视频任务（"看视频赚金币 - 5860"）
6. 首页额外刷视频 3-8 分钟

**总耗时：** ~9 分钟  
**单次收益：** ~15000-25000 金币（折合约 1.5-2.5 元现金）

### `scripts/ksjsb_watch.py` — 视频刷页工具

```bash
# 刷视频 N 分钟（自动上滑翻页 + 偶尔点赞）
python scripts/ksjsb_watch.py watch 8

# 截屏
python scripts/ksjsb_watch.py check

# 单独翻页 / 点赞
python scripts/ksjsb_watch.py swipe
python scripts/ksjsb_watch.py like
```

## 关键设计决策

### ⚠️ WebView 点击问题

**问题**：`adb shell input tap <x> <y>` 对快手任务中心 H5 WebView 元素经常无效。

**原因**：快手用 WebView 渲染任务中心 HTML 页面，WebView 对 `input tap` 的 MotionEvent 处理和 native View 不同。

**解法**：用极短距 `swipe`（1px 距离，50-100ms）代替 `tap`：

```python
def swipe_tap(x, y, ms=50):
    """1px swipe = 模拟精准 tap，比 input tap 在 WebView 上更可靠"""
    sh("input", "swipe", str(int(x)), str(int(y)),
       str(int(x)+1), str(int(y)+1), str(ms))
```

### ⚠️ "去观看"跳转直播间

**问题**：任务中心的"去观看"按钮有时跳到 `LiveSlideActivity`（直播间）而不是视频 feed。

**解法**：点击后检测 activity 名：

```python
focus = get_screen_info()["focus"]
if "LiveSlideActivity" in focus:
    back(2)  # 退回任务中心
```

### ⚠️ 广告跳应用商店

**问题**：看完"点可领 X 金币"后，广告页面的"领取奖励"按钮有时跳到 OPPO App Store（com.heytap.market）而不是回任务中心。

**解法**：
1. 检测 focus 不在 `AwardVideoPlayActivity` 时按 `am force-stop` 关掉 App Store
2. 重新 `am start -n com.kuaishou.nebula/...` 启动快手
3. 点"去赚钱" tab 回任务中心

### ⚠️ 弹窗遮挡

**问题**：任务中心频繁弹出"瓜分百亿"、"立即参与"、"领现金"等营销弹窗。

**解法**：连续按 `KEYCODE_BACK` 1-3 次关闭大多数弹窗。

### ⚠️ 锁屏断连

**问题**：手机锁屏后 ADB 会变成 `unauthorized`，脚本无法继续。

**解法**：
1. 跑脚本前 `adb shell input keyevent KEYCODE_WAKEUP` 唤醒屏幕
2. 检测到 `unauthorized` 时 `adb kill-server` + `adb start-server` 重连
3. 任务跑完后 `adb shell input keyevent KEYCODE_POWER` 重新锁屏

### ⚠️ 通知中心干扰

**问题**：状态栏下拉会变成 `NotificationShade`，脚本 swipe 会被劫持。

**解法**：
```bash
adb shell service call statusbar 1  # 收起通知中心
```

### ⚠️ 坐标系统

- `displayHeight=2400`（物理像素）vs `UI dump bounds max y=2285`（dp）
- 所有 UI 元素坐标基于 UI dump 的 `bounds` 值
- 直接用中心点 `(x1+x2)//2, (y1+y3)//2`，不需要做转换

## 任务优先级（按收益/时间）

| 任务 | 耗时 | 收益 | 优先级 |
|------|------|------|--------|
| 每日签到 | 5秒 | ~9888+ | ⭐⭐⭐⭐⭐ |
| 视频任务（"去观看"） | 8分钟 | 5860 | ⭐⭐⭐⭐ |
| 待领金币浮窗 | 3秒 | 200-4000 | ⭐⭐⭐⭐ |
| 宝箱（"点可领"） | 30秒/个 | 1000-3000 | ⭐⭐⭐⭐ |
| 看广告 | 30秒/个 | 200-800 | ⭐⭐ |
| 首页刷视频 | 5-8分钟 | 1000-3000 | ⭐⭐ |

## 自动化建议

- **每天 00:05-00:30** 之间跑效果最佳（0点刷新后第一时间）
- **搭配 cron**：每天 09:05 自动跑 `run-all`
- **手机保持 USB 连接和屏幕常亮**（不锁屏）
- **首次需用户确认** USB 调试授权

## 踩坑记录

详见 `references/troubleshooting.md`。

主要踩过的坑：
1. `adb shell input tap` 对 WebView 无效 → 用 1px `swipe`
2. uiautomator2 init 卡在下载 app-uiautomator.apk（404）→ 改用 adb 命令行
3. APK 安装弹窗"解析程序包时出现问题"→ `am force-stop` 后 `monkey -c LAUNCHER 1` 重启
4. 拼多多广告每次点"领取"都跳 App Store → 直接 `BACK` 退出，不领那 200 金币

## 目录结构

```
ksjsb-sign/
├── SKILL.md              # 本文件
├── scripts/
│   ├── ksjsb_auto.py     # 主自动化（签到/宝箱/视频/广告）
│   ├── ksjsb_watch.py    # 视频刷页工具
│   └── ksjsb_loop.py     # 持续循环跑金币（适合 cron / 任务计划）
└── references/
    ├── troubleshooting.md  # 踩坑记录（16 个坑）
    ├── task-center-ui.md   # 任务中心 UI 元素坐标
    └── cron-setup.md       # 定时任务配置
```

## 持续循环跑（金矿模式）

如果想 24 小时不停跑金币，用 `ksjsb_loop.py`：

```bash
# 默认每 10 分钟一轮
python scripts/ksjsb_loop.py

# 自定义间隔
python scripts/ksjsb_loop.py --interval 5

# 调试用：跑 3 轮后退出
python scripts/ksjsb_loop.py --max 3
```

**自动行为：**
- 设备掉线自动等 60s 重试
- 任务崩溃自动 force-stop + 重启快手
- 连续 3 轮无增长 → 进入长间隔等待（任务已做完）
- 写日志到 `ksjsb_loop.log`

**配合 cron / 任务计划程序：**
- Linux systemd 持续运行
- Windows 任务计划程序 - 触发器设为"登录时"，"如果任务失败，按以下频率重新启动：1 分钟"
- OpenClaw 用 `sessions_spawn` 起子 agent

详细配置见 `references/cron-setup.md`。
