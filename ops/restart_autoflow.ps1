# FACTORY（总调度 11-02 19:4x）：重启笔记本上的剧本写作推进常驻服务 tools/factory/autoflow_resident.py（单实例锁 data/factory/autoflow_resident.lock）
# 先停旧的（锁里记的 pid + 它的子进程），确认锁已释放 / 进程已退，再起新的；心跳 data/factory/autoflow_resident.json
$Root = "D:\NS-Final Studio"
$Lock = Join-Path $Root "data\factory\autoflow_resident.lock"
$Hb = Join-Path $Root "data\factory\autoflow_resident.json"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "autoflow_resident.py" } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction Stop } catch {} }
$deadline = (Get-Date).AddSeconds(15)
while ((Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "autoflow_resident.py" }) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
if (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "autoflow_resident.py" }) { Write-Host "旧的 autoflow_resident 还在，不启动新的"; exit 2 }
if (Test-Path $Lock) { Remove-Item $Lock -Force -Confirm:$false }   # 进程已全部退出：锁是陈旧的
Start-Process -WindowStyle Hidden -WorkingDirectory $Root -FilePath "$Root\.venv\Scripts\python.exe" `
    -ArgumentList "-X", "utf8", "tools/factory/autoflow_resident.py", "--interval", "30" `
    -RedirectStandardOutput "$Root\ops\logs\autoflow_resident.out.log" -RedirectStandardError "$Root\ops\logs\autoflow_resident.err.log"
for ($i = 0; $i -lt 40; $i++) { Start-Sleep -Milliseconds 500; if ((Test-Path $Hb) -and ((Get-Item $Hb).LastWriteTime -gt (Get-Date).AddSeconds(-20))) { Write-Host "autoflow_resident up"; exit 0 } }
Write-Host "autoflow_resident 没有写心跳"; exit 1
