# 稳定通道切换（PW-019）。总调度安排时间后再跑：切换时项目方的页面会断一下，然后自动刷新到稳定版。
#   pwsh switch.ps1            切换：开发服务器 → :5174；:5173 → 稳定版（只放过了 gate.sh 的构建）；启动 15 分钟构建器
#   pwsh switch.ps1 -Rollback  回退：停掉稳定版，:5173 恢复成开发服务器（:5174 的开发服务器保留也无妨）
param([switch]$Rollback)
$ErrorActionPreference = "Stop"
$Root = "D:\NS-Final Studio"
$Web = Join-Path $Root "apps\web"
$St = Join-Path $Web "e2e\uimaster\stable"
$Logs = Join-Path $Root "ops\logs"
New-Item -ItemType Directory -Force $Logs | Out-Null
function PidOn([int]$Port) { (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess }
function WaitHttp([string]$Url, [int]$Sec = 60) {
  for ($i = 0; $i -lt $Sec; $i++) { try { $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -eq 200) { return $true } } catch {} ; Start-Sleep 1 }
  return $false
}
function StopTree([int]$ProcId) { if ($ProcId) { & taskkill.exe /PID $ProcId /T /F | Out-Null } }

if ($Rollback) {
  "回退：停掉 :5173 上的稳定版，恢复开发服务器" | Write-Output
  StopTree (PidOn 5173)
  Start-Process -WindowStyle Hidden -FilePath "cmd.exe" -ArgumentList "/c", "cd /d `"$Web`" && npx vite --port 5173 --strictPort >> `"$Logs\web_dev.log`" 2>&1"
  if (WaitHttp "http://127.0.0.1:5173/src/main.tsx") { "已回退：:5173 = 开发服务器" } else { throw ":5173 开发服务器没起来，看 $Logs\web_dev.log" }
  return
}

# 0) 先确保有一份过了闸门的构建（没有就现在构建一次；闸门不过就不切）
if (-not (Test-Path (Join-Path $St "builds\current.txt"))) {
  & node (Join-Path $St "rebuild.mjs") --force "切换前首次构建"
  if (-not (Test-Path (Join-Path $St "builds\current.txt"))) { throw "没有过闸门的构建，不切换（看 $St\builds\rebuild.log）" }
}
# 1) 开发服务器起在 :5174（各 agent 用）
if (-not (PidOn 5174)) {
  Start-Process -WindowStyle Hidden -FilePath "cmd.exe" -ArgumentList "/c", "cd /d `"$Web`" && npx vite --port 5174 --strictPort >> `"$Logs\web_dev_5174.log`" 2>&1"
  if (-not (WaitHttp "http://127.0.0.1:5174/src/main.tsx")) { throw ":5174 开发服务器没起来，不切换（看 $Logs\web_dev_5174.log）" }
}
# 2) 停掉 :5173 上的开发服务器（项目方那个标签页会断线 → vite 客户端探测到 :5173 恢复后自动整页刷新）
StopTree (PidOn 5173)
Start-Sleep 1
# 3) :5173 起稳定版
Start-Process -WindowStyle Hidden -FilePath "node" -ArgumentList "`"$St\server.mjs`"" -RedirectStandardOutput "$Logs\stable_5173.log" -RedirectStandardError "$Logs\stable_5173.err.log"
if (-not (WaitHttp "http://127.0.0.1:5173/__stable" 20)) { "稳定版没起来，立刻回退"; & $PSCommandPath -Rollback; throw "切换失败，已回退" }
# 4) 15 分钟构建器（已在跑就不重复起）
$running = Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object { $_.CommandLine -like '*stable*rebuild.mjs*--loop*' }
if (-not $running) { Start-Process -WindowStyle Hidden -FilePath "node" -ArgumentList "`"$St\rebuild.mjs`"", "--loop" -RedirectStandardOutput "$Logs\stable_rebuild.log" -RedirectStandardError "$Logs\stable_rebuild.err.log" }
"已切换：:5173 = 稳定版（$((Invoke-WebRequest http://127.0.0.1:5173/__stable -UseBasicParsing).Content)），:5174 = 开发服务器，构建器每 15 分钟检查一次"
