# FACTORY（总调度 11-02 19:5x）：重启笔记本上的 resident_sync loop（常驻：健康检查 / control 推送 / 重启队列 / autoflow 报告线程 / 期望表同步）
# 单实例：先停掉所有 "resident_sync.py loop" 进程（含 .venv 转发器的子进程），确认全部退出再起一份；不碰任何暂停字段
$Root = "D:\NS-Final Studio"
$match = "resident_sync.py loop"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match [regex]::Escape($match) } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction Stop } catch {} }
$deadline = (Get-Date).AddSeconds(15)
while ((Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match [regex]::Escape($match) }) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
if (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match [regex]::Escape($match) }) { Write-Host "旧的 resident_sync loop 还在，不启动新的"; exit 2 }
Start-Process -WindowStyle Hidden -WorkingDirectory $Root -FilePath "$Root\.venv\Scripts\python.exe" `
    -ArgumentList "-u", "tools/autopilot/resident_sync.py", "loop" `
    -RedirectStandardOutput "$Root\ops\logs\resident_sync.loop.out.log" -RedirectStandardError "$Root\ops\logs\resident_sync.loop.err.log"
Start-Sleep -Seconds 3
$n = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match [regex]::Escape($match) -and $_.ExecutablePath -match "\.venv\\" }).Count
Write-Host "resident_sync loop 已起（.venv 进程 $n 个，应为 1）"
