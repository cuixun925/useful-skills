# Cron 自动化配置

让 ksjsb-sign 每天自动跑，配合 0 点任务刷新规律。

## 最佳执行时间

快手极速版任务在每天 **00:00** 刷新，建议跑脚本的时间：

| 时间 | 说明 |
|------|------|
| 00:05-00:30 | 🥇 最佳 - 0点刷新后第一时间（部分用户反馈）|
| 09:00-09:30 | 🥈 早晨 - 0点刷新完睡醒做 |
| 12:00-12:30 | 🥉 午间 - 0点刷新后半天 |
| 20:00-21:00 | 晚间补刀 |

## 一次性执行（每天同一时间）

### Linux/Mac（crontab）

```bash
# 编辑 crontab
crontab -e

# 每天 09:05 跑一次（追加这行）
5 9 * * * cd /path/to/ksjsb-sign/scripts && /usr/bin/python3 ksjsb_auto.py run-all >> /path/to/ksjsb-sign/cron.log 2>&1
```

### Windows（任务计划程序）

```powershell
# 创建每日 09:05 任务
$action = New-ScheduledTaskAction `
    -Execute "C:\Program Files\Python312\python.exe" `
    -Argument "C:\Users\Administrator\.openclaw\scripts\ksjsb_auto.py run-all" `
    -WorkingDirectory "C:\Users\Administrator\.openclaw\scripts"

$trigger = New-ScheduledTaskTrigger -Daily -At "09:05"

Register-ScheduledTask `
    -TaskName "ksjsb_daily_earn" `
    -Action $action `
    -Trigger $trigger `
    -User "SYSTEM" `
    -RunLevel Highest
```

## 持续循环执行（24小时不停地跑）

适合"金矿模式"——子 agent 持续跑，每 5-10 分钟一遍。

### Linux/Mac（systemd）

```ini
# /etc/systemd/system/ksjsb-looper.service
[Unit]
Description=ksjsb auto loop earn coins
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /path/to/ksjsb-sign/scripts/ksjsb_auto.py run-all
Restart=always
RestartSec=600
User=root

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable ksjsb-looper
systemctl start ksjsb-looper
systemctl status ksjsb-looper
```

### Windows（任务计划程序 - 持续模式）

```powershell
# 创建"开机启动 + 持续循环"任务
$action = New-ScheduledTaskAction `
    -Execute "C:\Program Files\Python312\pythonw.exe" `
    -Argument "C:\Users\Administrator\.openclaw\scripts\ksjsb_loop.py"

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "ksjsb_loop" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -User "$env:USERNAME" `
    -RunLevel Highest
```

## OpenClaw 用户（推荐）

OpenClaw 自带 cron，直接用 sessions_spawn 起子 agent：

```python
# 在 OpenClaw 主 session 中
sessions_spawn(
    task="""持续帮用户在快手极速版赚金币，不要停...
    (详细的子 agent prompt，见 SKILL.md)""",
    taskName="ksjsb_coin_earner",
    mode="run"
)
```

## 监控日志

### 关键指标

| 指标 | 正常值 | 异常处理 |
|------|--------|----------|
| 设备连接 | `device` | unauthorized → 用户解锁手机 |
| 当前 focus | HomeActivity / AwardVideoPlayActivity | App Store → force-stop |
| 金币增量 | 每轮 +1000 ~ +10000 | 0 增长 → 任务做完，等下一轮 |
| 脚本运行时间 | 30s ~ 5min | 超时 → kill 进程 + 重启 |
| CPU 占用 | < 30% | 持续高 → 检查死循环 |

### 日志格式

```python
import logging
from pathlib importPath

log_path = Path("./ksjsb_earn.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("ksjsb")

# 关键节点打日志
log.info(f"设备 {device_id} focus={focus}")
log.info(f"领金币 +{coins} → 总 {total}")
log.info(f"宝箱开启 {n}/20, 冷却剩余 {cooldown}s")
```

## 异常告警

### 设备 unauthorized 告警

```python
def check_device():
    r = subprocess.run([ADB, "devices"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if device_id in line and "device" in line and "unauthorized" not in line:
            return True
    return False

if not check_device():
    # 发送通知给用户（飞书/微信/Telegram）
    send_alert(f"📱 快手设备掉线，请解锁手机确认 USB 调试！")
    time.sleep(60)  # 等 1 分钟
    return  # 不强行重试
```

### 脚本崩溃恢复

```python
# 用 try/except 包住主循环
while True:
    try:
        run_one_round()
    except Exception as e:
        log.exception("本轮崩溃")
        # 强制恢复
        subprocess.run([ADB, "shell", "am", "force-stop", "com.kuaishou.nebula"])
        time.sleep(5)
        subprocess.run([ADB, "shell", "am", "start", "-n", 
                       "com.kuaishou.nebula/com.yxcorp.gifshow.HomeActivity"])
        time.sleep(10)
        # 继续下一轮
```

## 关闭自动化

### 临时停止

```bash
# Linux
systemctl stop ksjsb-looper

# Windows
Stop-ScheduledTask -TaskName "ksjsb_daily_earn"
```

### 完全删除

```bash
# Linux
systemctl disable ksjsb-looper
rm /etc/systemd/system/ksjsb-looper.service

# Windows
Unregister-ScheduledTask -TaskName "ksjsb_daily_earn" -Confirm:$false
```

### 关闭子 agent（OpenClaw）

```python
# 在主 session 中
sessions_send(
    sessionKey="agent:main:subagent:xxx",
    message="任务完成，停止运行"
)
```
