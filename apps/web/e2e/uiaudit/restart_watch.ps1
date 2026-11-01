# UIAUDIT 冷启动守候：轮询 data/qa/api_restart.json，up_at 一变就立刻并发 3 个 /api/episodes，70 s 后再测一次，结果追加到 restart_watch.log。
# 只读：只发 GET（带本机只读查看令牌）。用法：pwsh -File restart_watch.ps1 [-Hours 8]
param([double]$Hours = 8)
$root = Resolve-Path "$PSScriptRoot\..\..\..\.."
$flag = Join-Path $root "data\qa\api_restart.json"
$log = Join-Path $PSScriptRoot "restart_watch.log"
$tok = (Get-Content (Join-Path $root "data\auth\viewer_token")).Trim()
$sb = { param($t) $sw = [Diagnostics.Stopwatch]::StartNew(); try { $r = Invoke-WebRequest "http://127.0.0.1:8800/api/episodes" -Headers @{ "x-ns-viewer-token" = $t } -UseBasicParsing -TimeoutSec 120; "$($r.StatusCode)@$($sw.ElapsedMilliseconds)ms snap=$($r.Headers['x-ns-snapshot'])" } catch { "ERR@$($sw.ElapsedMilliseconds)ms" } }
$last = if (Test-Path $flag) { (Get-Content $flag -Raw | ConvertFrom-Json).up_at } else { $null }
"$(Get-Date -Format s) 开始守候，当前 up_at=$last" | Add-Content $log -Encoding utf8
$end = (Get-Date).AddHours($Hours)
while ((Get-Date) -lt $end) {
  Start-Sleep -Milliseconds 250
  if (-not (Test-Path $flag)) { continue }
  try { $j = Get-Content $flag -Raw | ConvertFrom-Json } catch { continue }
  if (-not $j.up_at -or $j.up_at -eq $last) { continue }
  $last = $j.up_at
  $t0 = Get-Date -Format "HH:mm:ss.fff"
  $jobs = 1..3 | ForEach-Object { Start-ThreadJob -ScriptBlock $sb -ArgumentList $tok }
  $r0 = ($jobs | Wait-Job | Receive-Job) -join " | "
  "$(Get-Date -Format s) 重启 up_at=$($j.up_at) by=$($j.by)；检测到 $t0，T+0 并发×3：$r0" | Add-Content $log -Encoding utf8
  Start-Sleep 70
  $jobs = 1..3 | ForEach-Object { Start-ThreadJob -ScriptBlock $sb -ArgumentList $tok }
  "$(Get-Date -Format s)   T+70 并发×3：$(($jobs | Wait-Job | Receive-Job) -join ' | ')" | Add-Content $log -Encoding utf8
}
