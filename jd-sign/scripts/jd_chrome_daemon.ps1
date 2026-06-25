# 京东 Chrome 常驻程序 - 启动并保持 Chrome 运行
# 使用独立 Profile + CDP 端口，保持登录态
# 支持无头/有头模式切换

param(
    [int]$debugPort = 9222,
    [string]$profile = "C:\Users\Administrator\.openclaw\chrome-sign-profile",
    [switch]$headless = $false,
    [switch]$check = $false
)

$ErrorActionPreference = "Continue"
$logFile = "C:\Users\Administrator\.openclaw\workspace\jd_chrome_daemon.log"

function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Out-File -FilePath $logFile -Append -Encoding UTF8
    # 终端输出用 ASCII 过滤后的版本（避免 GBK 环境乱码）
    $safe = $msg -replace '[^\x20-\x7E]', ''
    Write-Host $safe
}

# 检查 Chrome 是否已在运行
function Test-ChromeRunning($port) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$port/json" -TimeoutSec 3 -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

# 健康检查模式
if ($check) {
    $running = Test-ChromeRunning $debugPort
    if ($running) {
        Log "HEALTH_CHECK: Chrome running on port $debugPort"
        exit 0
    } else {
        Log "HEALTH_CHECK: Chrome NOT running on port $debugPort"
        exit 2
    }
}

Log "===== JD Chrome Daemon Start ====="
Log "Profile: $profile"
Log "Debug Port: $debugPort"
Log "Headless: $headless"

# 如果 Chrome 已在该端口运行，直接退出（不重复启动）
if (Test-ChromeRunning $debugPort) {
    Log "Chrome already running on port $debugPort, skip start"
    exit 0
}

# 杀掉可能存在的旧 Chrome 进程（清理遗骸）
Log "Cleaning up old Chrome processes..."
Stop-Process -Name chrome -Force -ErrorAction SilentlyContinue
Start-Sleep 3

# 创建/确保 Profile 目录存在
if (-not (Test-Path $profile)) {
    New-Item -ItemType Directory -Path $profile -Force | Out-Null
    Log "Created Profile directory: $profile"
}

# 启动 Chrome
$chromeArgs = @(
    "--remote-debugging-port=$debugPort",
    "--user-data-dir=$profile",
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check"
)
if ($headless) {
    $chromeArgs += "--headless=new"
}

Log "Starting Chrome..."
$proc = Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    -ArgumentList $chromeArgs `
    -WindowStyle Hidden -PassThru

Start-Sleep 5

# 等待 CDP 端口就绪
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    if (Test-ChromeRunning $debugPort) {
        $ready = $true
        break
    }
    Start-Sleep 1
}

if ($ready) {
    Log "CDP port ready (port $debugPort)"
    Log "Chrome PID: $($proc.Id)"
    Log "===== Chrome Daemon Started ====="
    exit 0
} else {
    Log "[ERROR] CDP port NOT ready after 20s"
    exit 1
}
