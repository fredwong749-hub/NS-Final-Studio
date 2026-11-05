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
$AfHb = Join-Path $Root "data\factory\autoflow_resident.json"
$AfLock = Join-Path $Root "data\factory\autoflow_resident.lock"
$AfRestart = Join-Path $Root "ops\restart_autoflow.ps1"
$afNext = [datetime]::MinValue
$HealthHb = Join-Path $Root "data\master\health\health.json"                 # SELF-HEAL：autoflow_resident 里的健康线程每 ≤60 s 写；超过 5 分钟没写 = 线程死了
$HealthFlag = Join-Path $Root "data\master\health\want_restart_autoflow.json"  # 健康线程发现 autoflow 跑的是旧代码时写旗（它不杀自己）
$RelLock = Join-Path $Root "data\system_versions\release_lock.json"
$CutLock = Join-Path $Root "data\system_versions\cut_lock.json"
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
# W17b P1-2（A17 第 28 轮）：release（cut / deploy 是 resident_sync 的子进程）进行中不杀进程树，等它跑完再判。
# 进行中 = release_lock.json 的 pid 还活着且未过 6 h TTL（与 release_tick.LOCK_TTL_S 同），或 cut_lock.json active 且未到期（cut 期间每 5 分钟续期）
function ReleaseBusy {
  try {
    if (Test-Path $RelLock) {
      $r = Get-Content $RelLock -Raw -Encoding utf8 | ConvertFrom-Json
      $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [double]$r.t
      if ($r.pid -and $age -lt 6 * 3600 -and (Get-Process -Id ([int]$r.pid) -ErrorAction SilentlyContinue)) { return "release_lock pid $($r.pid)（$($r.what)）" }
    }
    if (Test-Path $CutLock) {
      $c = Get-Content $CutLock -Raw -Encoding utf8 | ConvertFrom-Json
      if ($c.active -and [double]$c.expires_t -gt [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) { return "cut_lock active（$($c.sv)，pid $($c.pid)）" }
    }
  } catch { return $null }       # 锁文件坏 / 读不到 = 不算进行中（退回旧行为）
  return $null
}

# ISS-1103-172950-44d8：autoflow_resident 被外部杀过两次、看门狗跑在它里面救不了自己 → 本守护兜底。
# 心跳 data/factory/autoflow_resident.json 的 at 超过 3 分钟没拍，且锁里记的 pid 不在 → 调 ops/restart_autoflow.ps1（它只停锁里记的 pid，不按命令行杀）。
# 一轮最多一次；失败后 3 分钟内不再试。
function AutoflowDown {
  try {
    if (-not (Test-Path $AfHb)) { return $false }
    $at = [datetime]::Parse(((Get-Content $AfHb -Raw -Encoding utf8 | ConvertFrom-Json).at))
    if (((Get-Date) - $at).TotalMinutes -le 3) { return $false }
  } catch { return $false }
  try {
    if (Test-Path $AfLock) {
      $lp = [int]((Get-Content $AfLock -Raw -Encoding utf8 | ConvertFrom-Json).pid)
      if ($lp -and (Get-Process -Id $lp -ErrorAction SilentlyContinue)) { return $false }
    }
  } catch { }
  return $true
}
# SELF-HEAL 11-05（FIX-B 复核加固）：autoflow 进程在、心跳也新，但 (a) 健康线程死了 或 (b) 健康线程写了“要重启”旗 → 也走 restart_autoflow.ps1（只停锁里 pid）。
# 加固：(a) 只有在 health.json 里的 pid == autoflow 心跳 pid（同一个进程写的）、且该进程已运行 > 10 分钟时才判“线程死了”（刚起的进程 / 别的进程写的 health.json 不算）；
#       自愈类重启（非“进程已死”）退避 + 每小时上限：每次重启后下一次最早 = 10 分钟 * 2^已重启次数；一小时内最多 $AfHealMax 次，超了只记日志不再重启（交总调度看）。
$AfHealMax = 2
$afHealTimes = @()
function AutoflowWanted {
  try {
    $hb = $null
    if (Test-Path $AfHb) { $hb = Get-Content $AfHb -Raw -Encoding utf8 | ConvertFrom-Json }
    if ($null -eq $hb) { return $null }
    $up = $null
    $proc = Get-Process -Id ([int]$hb.pid) -ErrorAction SilentlyContinue
    if ($proc) { $up = ((Get-Date) - $proc.StartTime).TotalMinutes }
    if ($null -eq $up -or $up -le 10) { return $null }     # 进程不在（走原“心跳死 + pid 不在”路径）或刚起 10 分钟内：不做自愈判断
    if (Test-Path $HealthFlag) { return "健康线程要求重启（旗 want_restart_autoflow.json）" }
    if (Test-Path $HealthHb) {
      $h = Get-Content $HealthHb -Raw -Encoding utf8 | ConvertFrom-Json
      $hbAge = ((Get-Date) - [datetime]::Parse($hb.at)).TotalMinutes
      $hAge = ((Get-Date) - (Get-Item $HealthHb).LastWriteTime).TotalMinutes
      if ([int]$h.pid -eq [int]$hb.pid -and $hbAge -le 3 -and $hAge -gt 5) { return "autoflow 心跳正常但 health.json $([int]$hAge) 分钟没更新（同一 pid $($hb.pid) 的健康线程死了，已运行 $([int]$up) 分钟）" }
    }
  } catch { }
  return $null
}
function AutoflowGuard {
  if ((Get-Date) -lt $afNext) { return }
  $want = AutoflowWanted
  $down = AutoflowDown
  if (-not $down -and -not $want) { return }
  if (-not $down -and $want) {
    $script:afHealTimes = @($afHealTimes | Where-Object { $_ -gt (Get-Date).AddHours(-1) })
    if ($afHealTimes.Count -ge $AfHealMax) {
      $script:afNext = (Get-Date).AddMinutes(10)
      Log "autoflow 自愈重启一小时内已达上限 $AfHealMax 次，不再重启（$want）——交总调度看"
      return
    }
    Log "autoflow 需要重启：$want"
    if (Test-Path $HealthFlag) { Move-Item $HealthFlag ($HealthFlag + "." + (Get-Date -Format "yyyyMMddHHmmss") + ".done") -Force -ErrorAction SilentlyContinue }   # 不删，改名留账
    $script:afHealTimes = @($afHealTimes) + (Get-Date)
    $script:afNext = (Get-Date).AddMinutes(10 * [math]::Pow(2, $afHealTimes.Count - 1))      # 退避：10 / 20 分钟
  } else {
    $script:afNext = (Get-Date).AddMinutes(3)
    Log "autoflow_resident 心跳超过 3 分钟没拍且锁里 pid 不在：调 ops/restart_autoflow.ps1"
  }
  try { & powershell -NoProfile -ExecutionPolicy Bypass -File $AfRestart | Out-Null; Log "restart_autoflow.ps1 退出码 $LASTEXITCODE" } catch { Log "restart_autoflow.ps1 调用失败：$($_.Exception.Message)" }
}


# SELF-HEAL 11-05：互相拉起——另一个守护（monitor_guard）不在就用计划任务把它起来（计划任务单实例 + 命名互斥体，重复起无害）。每 2 分钟最多一次。
$peerNext = [datetime]::MinValue
function PeerGuard {
  if ((Get-Date) -lt $peerNext) { return }
  $up = Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='pwsh.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "monitor_guard\.ps1" }
  if ($up) { return }
  $script:peerNext = (Get-Date).AddMinutes(2)
  Log "守护 monitor_guard 不在：Start-ScheduledTask NS-Studio-Monitor-Guard"
  try { Start-ScheduledTask -TaskName "NS-Studio-Monitor-Guard" -ErrorAction Stop } catch { Log "拉起 NS-Studio-Monitor-Guard 失败：$($_.Exception.Message)" }
}

Log "守护启动 pid $PID"
while ($true) {
  PeerGuard
  AutoflowGuard
  $p = Procs
  if ($p -and (TickStale)) {
    $busy = ReleaseBusy
    if ($busy) {
      Log "last_tick.json 超过 25 分钟没更新，但 release 进行中（$busy）：不杀，等它跑完"
    } else {
      Log "last_tick.json 超过 25 分钟没更新：判 loop 卡死，杀进程树重拉"
      foreach ($x in $p) { & taskkill /PID $x.ProcessId /T /F | Out-Null }
      $p = $null
    }
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
