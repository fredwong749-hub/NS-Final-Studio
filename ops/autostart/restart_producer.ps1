# PRODUCER 制作监督安全重载（11-01）：先暂停 → 等在做的出图 / 打分做完（heartbeat inflight = 0，最多等 3 分钟）
# → 停掉启动器和子进程（.venv\Scripts\python.exe 是启动器，会再起一个子进程）→ 重新拉起 → 恢复原来的暂停状态。
# 直接杀进程会让在跑的 ComfyUI 任务出完了却没人登记（11-01 04:42 实际发生过：7 个尝试白跑）。
# PRODMERGE-O 11-03（PLAN_V2_MASTER v4 1-5）：按剧运行——-Run 不给 = runs.json 的 primary（当前剧唯一来源）；
# control / heartbeat / pid 目录 = runs.producer_dir（legacy 剧 data\producer，其它剧 data\producer\runs\<剧>）；pause / resume / serve 都带 --run。
param([string]$Run = "")
$ErrorActionPreference = "Continue"
$Root = "D:\NS-Final Studio"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$env:PYTHONUTF8 = "1"
$reg = Get-Content (Join-Path $Root "config\pipeline\runs.json") -Raw | ConvertFrom-Json
if (-not $Run) { $Run = [string]$reg.primary }
if (-not $Run -or -not ($reg.runs.PSObject.Properties.Name -contains $Run)) { Write-Error "restart_producer: 剧 '$Run' 不在 config\pipeline\runs.json"; exit 2 }
$Pd = if ($Run -eq [string]$reg.legacy_unprefixed_run) { Join-Path $Root "data\producer" } else { Join-Path $Root "data\producer\runs\$Run" }
$ctrlPath = Join-Path $Pd "control.json"
$wasPaused = $false
if (Test-Path $ctrlPath) { try { $wasPaused = [bool]((Get-Content $ctrlPath -Raw | ConvertFrom-Json).paused) } catch { } }
& $Py (Join-Path $Root "tools\autopilot\producer.py") pause --run $Run --by "restart_producer" --kind ops --expires-s 180 | Out-Null   # K-OPS-E08：运维暂停 ≤180 s，到点自动恢复
$deadline = (Get-Date).AddMinutes(3)   # K-OPS-E08（11-02）：运维暂停上限 180 s，等不满就重启（在途单靠租约过期 / 重派恢复）
while ((Get-Date) -lt $deadline) {
  try { $hb = Get-Content (Join-Path $Pd "heartbeat.json") -Raw | ConvertFrom-Json } catch { $hb = $null }
  if ($hb -and [int]$hb.inflight -eq 0) { break }
  Start-Sleep 10
}
$pidFile = Join-Path $Pd "producer.pid"
if (Test-Path $pidFile) {
  $c = (Get-Content $pidFile -Raw | ConvertFrom-Json).pid
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$c" -ErrorAction SilentlyContinue
  if ($proc -and $proc.CommandLine -match "producer.py") {
    $ids = @($c)
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)" -ErrorAction SilentlyContinue
    if ($parent -and $parent.CommandLine -match "producer.py") { $ids += $parent.ProcessId }
    Stop-Process -Id $ids -Confirm:$false -ErrorAction SilentlyContinue
  }
}
Start-Sleep 2
$log = Join-Path $Root "ops\logs\producer_$Run"
Start-Process -WindowStyle Hidden -WorkingDirectory $Root -FilePath $Py -ArgumentList "-u", "tools/autopilot/producer.py", "serve", "--run", $Run `
  -RedirectStandardOutput "$log.out.log" -RedirectStandardError "$log.err.log"
Start-Sleep 5
if (-not $wasPaused) { & $Py (Join-Path $Root "tools\autopilot\producer.py") resume --run $Run --by "restart_producer" | Out-Null }
Write-Output "producer[$Run] restarted (paused before: $wasPaused)"
