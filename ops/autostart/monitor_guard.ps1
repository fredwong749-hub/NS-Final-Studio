# 笔记本监控自启守护（L-106：项目方 11-02 03:2x 原话“允许笔记本监控自启”；总调度派 SENTINEL 落地）
# 守两件：SENTINEL 守护进程（tools/sentinel/sentinel.py serve，K-OPS-S02…S07）和 8810 看板（tools/monitor/server.py，GPU 采集走 rssh、30 s）。
# 计划任务 NS-Studio-Monitor-Guard（登录时启动；任务本身失败由计划任务每 1 分钟重启，最多 999 次）拉起本脚本；
# 本脚本常驻、每 60 s 检查一次，进程不在就拉起，连续失败按 60 → 120 → 240 … 最多 900 s 退避。单实例（命名互斥体）。
# 只拉起本机两个只读监控进程，不碰生产进程。日志：ops/logs/monitor_guard.log
$ErrorActionPreference = "Continue"
$Root = "D:\NS-Final Studio"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Logs = Join-Path $Root "ops\logs"
New-Item -ItemType Directory -Force $Logs | Out-Null
function Log($m) { Add-Content -Path (Join-Path $Logs "monitor_guard.log") -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) -Encoding utf8 }

$mtx = New-Object System.Threading.Mutex($false, "Global\NS-Studio-Monitor-Guard")
if (-not $mtx.WaitOne(0)) { Log "已有守护实例，退出"; exit 0 }

$env:PYTHONIOENCODING = "utf-8"
$jobs = @(
  @{ name = "sentinel"; match = "tools[\\/]sentinel[\\/]sentinel\.py.*serve"; args = @("-u", "tools/sentinel/sentinel.py", "serve"); out = "sentinel_serve" },
  @{ name = "monitor8810"; match = "tools[\\/]monitor[\\/]server\.py"; args = @("-u", "tools/monitor/server.py"); out = "monitor_8810"; port = 8810 }
)
$fail = @{}; $next = @{}
foreach ($j in $jobs) { $fail[$j.name] = 0; $next[$j.name] = [datetime]::MinValue }

function Alive($j) {
  $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match $j.match }
  if (-not $procs) { return $false }
  if ($j.port) {   # 用 HTTP 实测（本机 Get-NetTCPConnection / netstat 看不到该监听，11-02 实测）
    try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 "http://127.0.0.1:$($j.port)/"; return ($r.StatusCode -eq 200) } catch { return $false }
  }
  return $true
}

Log "守护启动 pid $PID"
while ($true) {
  foreach ($j in $jobs) {
    if (Alive $j) { $fail[$j.name] = 0; continue }
    if ((Get-Date) -lt $next[$j.name]) { continue }
    Start-Process -WindowStyle Hidden -WorkingDirectory $Root -FilePath $Py -ArgumentList $j.args `
      -RedirectStandardOutput (Join-Path $Logs ($j.out + ".out.log")) -RedirectStandardError (Join-Path $Logs ($j.out + ".err.log"))
    $ok = $false
    for ($k = 0; $k -lt 12 -and -not $ok; $k++) { Start-Sleep 5; $ok = Alive $j }     # 最多等 60 s
    if ($ok) { Log "$($j.name) 已拉起"; $fail[$j.name] = 0 }
    else {
      $fail[$j.name] += 1
      $wait = [Math]::Min(900, 60 * [Math]::Pow(2, $fail[$j.name] - 1))
      $next[$j.name] = (Get-Date).AddSeconds($wait)
      Log "$($j.name) 拉起失败第 $($fail[$j.name]) 次，退避 $wait s"
    }
  }
  Start-Sleep 60
}
