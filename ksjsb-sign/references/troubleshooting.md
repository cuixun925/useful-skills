# 踩坑记录

ksjsb-sign 脚本开发过程中遇到的所有坑和解法，按问题分类。

## ADB 点击相关

### 坑 1: WebView 点击无效

**症状**：`adb shell input tap <x> <y>` 对快手任务中心 H5 WebView 元素没反应，元素识别到了但 tap 无效果。

**根因**：快手用 WebView 渲染任务中心 HTML 页面，WebView 对 `input tap` 的 MotionEvent 处理和 native View 不同。`input tap` 注入的是合成事件，WebView 不一定能正确识别。

**解法**：用极短距 `swipe`（1px 距离，50-100ms）代替 `tap`。原理：swipe 会触发完整 ACTION_DOWN → ACTION_MOVE → ACTION_UP 流程，WebView 能正确识别。

```python
def swipe_tap(x, y, ms=50):
    """1px swipe = 模拟精准 tap，比 input tap 在 WebView 上更可靠"""
    sh("input", "swipe", str(int(x)), str(int(y)),
       str(int(x)+1), str(int(y)+1), str(ms))
```

**关键参数**：
- 距离 1px（不能太大，否则会变成真实滑动）
- 时长 50-100ms（不能太长，否则会触发长按）
- x/y 是 UI dump bounds 中心点

### 坑 2: UI dump 拉不下来

**症状**：`adb pull /sdcard/ui.xml` 失败，提示文件不存在。

**根因**：uiautomator dump 是异步操作，刚 dump 完文件还没写完，或者 `pull` 命令在 Windows 上中文路径编码问题。

**解法**：
1. dump 后 `sleep 1` 等待
2. 用 `adb exec-out cat /sdcard/ui.xml` 替代 `pull` 直接读 binary 流
3. 失败就重试 3 次

### 坑 3: uiautomator2 init 失败

**症状**：`uiautomator2.init()` 卡在 `app-uiautomator.apk` 下载，回报 404。

**根因**：源 repo 改名了（`openatx/android-uiautomator2-server` → `openatx/atx-agent`），旧 URL 失效。

**解法**：**直接用 adb 命令行操作，不依赖 uiautomator2 Python 库**。`uiautomator dump` + `adb exec-out cat` 就够了。

## 应用跳转相关

### 坑 4: "去观看" 跳到直播间

**症状**：点"去观看"按钮（bounds [849,1842][1041,1941]）后，跳到 `LiveSlideActivity` 而不是视频 feed。

**根因**：快手"去观看"任务有时候会随机分配直播间而不是视频。

**解法**：检测到 `LiveSlide` 就 `BACK` 2 次退出，重试。

```python
info = get_screen_info()
if "LiveSlide" in info.get("focus", ""):
    back(2)
    # 重试找其他"去观看"入口
```

### 坑 5: 广告"领取"按钮跳 App Store

**症状**：看完拼多多/伊利广告后，绿色的"领取"按钮（中心约 (540, 1219)）tap 一下就跳到 `com.heytap.market` OPPO App Store。

**根因**：这些广告的"领取"按钮会触发下载 App 引导，点了就强制跳应用商店。广告 SDK 的"防作弊"机制。

**解法**：
- **保守做法**：检测到 `com.heytap.market` focus 就 `am force-stop` + 重启快手 + 重进任务中心
- **激进做法**：完全不领这个广告的奖励（200 金币性价比低），直接 BACK 退出

```python
# 检测到 App Store
if "com.heytap.market" in focus:
    sh("am", "force-stop", "com.heytap.market")
    time.sleep(1)
    sh("am", "start", "-n", "com.kuaishou.nebula/com.yxcorp.gifshow.HomeActivity")
```

### 坑 6: "继续赚钱"按钮跳视频 feed

**症状**：奖励弹窗底部"继续赚钱"按钮 tap 之后，跳到首页视频 feed 而不是任务中心。

**根因**：快手把这个按钮设计成"以视频为饵"引导用户刷视频。

**解法**：
- 弹窗奖励已经领了，"继续赚钱"按钮**不点**
- 用 `KEYCODE_BACK` 关闭弹窗，应该回任务中心
- 如果回不到，再用 `tap(756, 2269)` 点底部"去赚钱"tab

## 设备状态相关

### 坑 7: 锁屏断连

**症状**：手机锁屏后 `adb devices` 显示 `unauthorized`。

**根因**：锁屏后 USB 调试授权会失效，需要重新解锁确认。

**解法**：
- 跑脚本前 `adb shell input keyevent KEYCODE_WAKEUP` 唤醒
- 检测到 unauthorized 时让用户解锁确认
- 跑完后 `adb shell input keyevent KEYCODE_POWER` 重新锁屏

### 坑 8: 通知中心下拉干扰

**症状**：手抖下拉状态栏通知中心后，swipe 操作被劫持，脚本全乱。

**根因**：Android 通知中心接管触摸事件。

**解法**：`adb shell service call statusbar 1` 收起通知栏。

```python
def close_notification_shade():
    sh("service", "call", "statusbar", "1")  # 1 = collapse
    time.sleep(1)
```

### 坑 9: 弹窗遮挡

**症状**：任务中心频繁弹出"瓜分百亿"、"立即参与"、"领现金"等营销弹窗。

**解法**：连续按 `KEYCODE_BACK` 1-3 次关闭。

```python
def close_popups(max_attempts=5):
    for i in range(max_attempts):
        sh("input", "keyevent", "KEYCODE_BACK")
        time.sleep(0.5)
        sh("input", "keyevent", "KEYCODE_BACK")
        time.sleep(0.5)
        # 检查是否还在弹窗
        xml = ui_dump()
        for n in ET.parse(xml).iter("node"):
            t = n.get("text", "").strip()
            if any(kw in t for kw in ["瓜分", "立即参与", "立即签到", "奖励", "好礼"]):
                continue  # 还有弹窗，继续按
        break  # 弹窗关了
```

## 任务状态相关

### 坑 10: 宝箱冷却时间

**症状**：开完一个宝箱后，下次开"点可领 X 金币"按钮还在那但点了没反应（10 分钟内）。

**根因**：快手任务中心宝箱设计成 10 分钟一个，共 20 个/天。

**解法**：
- 记录每个宝箱的开启时间
- 倒计时结束再开下一个
- 倒计时期间可以去做其他任务（看视频、看广告）

### 坑 11: 任务奖励到账延迟

**症状**：点完"领取"按钮后，金币没立刻到账。

**根因**：快手后端异步处理，通常 1-3 秒内到账。

**解法**：
- 领取后 sleep 2-3 秒
- 截图确认金币数变化
- 没到账就再点一次

## 坐标系统

### 坑 12: displayHeight vs UI bounds

**症状**：`wm size` 报告 `displayHeight=2400`，但 UI dump bounds 报告 `max y=2285`。

**根因**：Android 把底部导航栏（~115px）算进 display，但 UI dump 不会包含导航栏。

**解法**：所有点击坐标用 **UI dump bounds 中心点** 算，不要用 display 坐标。

```python
# ✅ 正确：用 UI dump bounds
xml = ui_dump()
tree = ET.parse(xml)
for n in tree.iter("node"):
    bounds = n.get("bounds")  # e.g. "[540,1450][720,1530]"
    if bounds:
        bn = parse_bounds(bounds)  # (540, 1450, 720, 1530)
        cx = (bn[0] + bn[2]) // 2  # 630
        cy = (bn[1] + bn[3]) // 2  # 1490

# ❌ 错误：用 display 坐标（会被导航栏挡住）
tap(540, 2200)  # 可能点到导航栏的"我"按钮
```

## 环境配置

### 坑 13: Python 编码

**症状**：PowerShell 调用 Python 跑 stdout 输出中文乱码。

**根因**：Python 3 默认 stdout 编码是 GBK，Windows 控制台也是 GBK。

**解法**：
```powershell
$env:PYTHONIOENCODING = "utf-8"
python ksjsb_auto.py
```

或者在脚本开头：
```python
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
```

### 坑 14: 截图保存路径

**症状**：`adb exec-out screencap -p` 输出 PNG binary 写到 PowerShell 变量会被编码破坏。

**根因**：PowerShell 把 binary 当字符串处理。

**解法**：用 Python subprocess + 直接写文件：

```python
import subprocess
subprocess.run(
    [r"C:\platform-tools\adb.exe", "exec-out", "screencap", "-p"],
    stdout=open(r"C:\path\to\screenshot.png", "wb")
)
```

## 性能优化

### 坑 15: UI dump 慢

**症状**：每次 `uiautomator dump` 都要 1-2 秒，频繁 dump 脚本很慢。

**解法**：
- 减少 dump 频率（关键步骤才 dump）
- 用 focus 检测代替 dump（更快）
- 缓存上次的 UI 结构

### 坑 16: screencap 慢

**症状**：每次截图 200-500ms。

**解法**：
- 截图前先 `chmod 777` 确保权限
- 不要每步都截图，关键节点截图
- 用 `screencap -p` (PNG) 比 `screencap` (raw) 慢，但体积小
