# 总调度用：重启 :8800 ns_api，并写重启标记 data/qa/api_restart.json（UIAUDIT / PAGEWATCH 轮询它测冷启动）
# 只在 /api/jobs 没有 queued/running 时重启；-Force 跳过检查。
param([switch]$Force)
$Root = "D:\NS-Final Studio"
$Marker = Join-Path $Root "data\qa\api_restart.json"

if (-not $Force) {
    try {
        $r = Invoke-RestMethod http://127.0.0.1:8800/api/jobs -TimeoutSec 10
        $j = if ($r.jobs) { $r.jobs } else { $r }
        $busy = @($j | Where-Object { $_.state -in 'queued', 'running' }).Count
        if ($busy -gt 0) { Write-Host "busy $busy，不重启"; exit 1 }
    } catch { Write-Host "读 /api/jobs 失败，按未运行处理" }
}

$stopped = (Get-Date).ToString("s")
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "uvicorn ns_api.app:app" } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction Stop } catch {} }

# 守卫（总调度 19:3x，V2-WALK W-12）：确认 :8800 上的旧进程全部退出、端口空了才起新的；20 秒还占着就报错退出，不叠第二份
# 注：.venv\Scripts\python.exe 在 Windows 上是转发器，会再起一个系统 Python 子进程——父子两个算同一份服务，不是重复
$freeBy = (Get-Date).AddSeconds(20)
while ((Get-NetTCPConnection -LocalPort 8800 -State Listen -ErrorAction SilentlyContinue) -and (Get-Date) -lt $freeBy) { Start-Sleep -Milliseconds 300 }
if (Get-NetTCPConnection -LocalPort 8800 -State Listen -ErrorAction SilentlyContinue) {
    $holders = (Get-NetTCPConnection -LocalPort 8800 -State Listen | Select-Object -ExpandProperty OwningProcess) -join ","
    Write-Host "8800 端口仍被占用（进程 $holders），不启动新的 API"; exit 2
}

$env:NS_COMFY_URL = "http://127.0.0.1:18188"
Start-Process -WindowStyle Hidden -WorkingDirectory $Root -FilePath "$Root\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "ns_api.app:app", "--port", "8800", "--host", "127.0.0.1" `
    -RedirectStandardOutput "$Root\ops\logs\api_8800.out.log" -RedirectStandardError "$Root\ops\logs\api_8800.err.log"

$up = $null
for ($i = 0; $i -lt 60; $i++) {
    try { if ((Invoke-WebRequest http://127.0.0.1:8800/api/season -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { $up = (Get-Date).ToString("s"); break } } catch {}
}
@{ stopped_at = $stopped; up_at = $up; by = "master" } | ConvertTo-Json | Set-Content -Path $Marker -Encoding utf8
Write-Host "stopped $stopped  up $up"
