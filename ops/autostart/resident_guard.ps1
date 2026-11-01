# 笔记本 resident_sync loop 守护（WORKFLOW 11-02 04:1x，总调度派：“挂了能自动拉起，照 NS-Studio-Monitor-Guard 做”；规则 K-OPS-W22）
# 守一件：tools/autopilot/resident_sync.py loop（健康 / 重启队列 / 控制文件推送 / 并回 + DISTILL 编排器每拍 autoflow_tick 线程）。
# 计划任务 NS-Studio-ResidentSync-Guard（登录时启动；任务失败每 1 分钟重启，最多 999 次）拉起本脚本；
# 本脚本常驻、每 60 s 检查一次：进程不在就拉起；另查 data/autopilot/flow/last_tick.json，超过 25 分钟没更新（一拍上限 20 分钟）
# 视为 loop 卡死 → 杀掉整棵进程树再拉起。连续失败 60 → 120 → … 最多 900 s 退避。单实例（命名互斥体）。日志：ops/logs/resident_guard.log
$ErrorActionPreference = "Continue"
$Root = "D:\NS-Final Studio"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Logs = Join-Path $Root "ops\logs"
$Tick = Join-Path $Root "data\autopilot\flow\last_tick.json"
New-Item -ItemType Directory -Force $Logs | Out-Null
function Log($m) { Add-Content -Path (Join-Path $Logs "resident_guard.log") -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) -Encoding utf8 }

$mtx = New-Object System.Threading.Mutex($false, "Global\NS-Studio-ResidentSync-Guard")
if (-not $mtx.WaitOne(0)) { Log "已有守护实例，退出"; exit 0 }

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$match = "tools[\/]autopilot[\/]resident_sync\.py.*\bloop\b"
$fail = 0; $next = [datetime]::MinValue; $startedAt = [datetime]::MinValue

function Procs { Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match $match } }
function TickStale {
  if (((Get-Date) - $startedAt).TotalMinutes -lt 25) { return $false }      # 刚拉起的 25 分钟内不判
  if (-not (Test-Path $Tick)) { return $true }
  return (((Get-Date) - (Get-Item $Tick).LastWriteTime).TotalMinutes -gt 25)
}

Log "守护启动 pid $PID"
while ($true) {
  $p = Procs
  if ($p -and (TickStale)) {
    Log "last_tick.json 超过 25 分钟没更新：判 loop 卡死，杀进程树重拉"
    foreach ($x in $p) { & taskkill /PID $x.ProcessId /T /F | Out-Null }
    $p = $null
  }
  if (-not $p -and (Get-Date) -ge $next) {
    Start-Process -WindowStyle Hidden -WorkingDirectory $Root -FilePath $Py -ArgumentList @("-u", "tools/autopilot/resident_sync.py", "loop") `
      -RedirectStandardOutput (Join-Path $Logs "resident_sync.out.log") -RedirectStandardError (Join-Path $Logs "resident_sync.err.log")
    $ok = $false
    for ($k = 0; $k -lt 12 -and -not $ok; $k++) { Start-Sleep 5; $ok = [bool](Procs) }
    if ($ok) { Log "resident_sync loop 已拉起"; $fail = 0; $startedAt = Get-Date }
    else {
      $fail += 1
      $wait = [Math]::Min(900, 60 * [Math]::Pow(2, $fail - 1))
      $next = (Get-Date).AddSeconds($wait)
      Log "resident_sync loop 拉起失败第 $fail 次，退避 $wait s"
    }
  } elseif ($p) { $fail = 0; if ($startedAt -eq [datetime]::MinValue) { $startedAt = Get-Date } }
  Start-Sleep 60
}
