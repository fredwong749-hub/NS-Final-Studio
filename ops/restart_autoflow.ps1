# FACTORY（总调度 11-02 19:4x）：重启笔记本上的剧本写作推进常驻服务 tools/factory/autoflow_resident.py（单实例锁 data/factory/autoflow_resident.lock）
# AUTOFIX-O 11-03（K-OPS-F30）：只停锁里记的 pid（及其子进程），不再按命令行匹配杀进程；
# 新的一份用 autoflow_resident.py --detach 起（脱离调用方会话 / 作业对象，会话结束不会被整棵带走）；起停原因见 ops/logs/autoflow_resident.life.log
$Root = "D:\NS-Final Studio"
$Lock = Join-Path $Root "data\factory\autoflow_resident.lock"
$Hb = Join-Path $Root "data\factory\autoflow_resident.json"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$old = $null
if (Test-Path $Lock) { try { $old = [int]((Get-Content $Lock -Raw | ConvertFrom-Json).pid) } catch { $old = $null } }
if ($old) {
    if (Get-Process -Id $old -ErrorAction SilentlyContinue) { & taskkill /PID $old /T /F | Out-Null }
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Process -Id $old -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
    if (Get-Process -Id $old -ErrorAction SilentlyContinue) { Write-Host "锁里记的旧 autoflow_resident（pid $old）还在，不启动新的"; exit 2 }
}
if (Test-Path $Lock) { Remove-Item $Lock -Force -Confirm:$false }   # 锁主进程已退出：锁是陈旧的
$t0 = Get-Date
& $Py -X utf8 (Join-Path $Root "tools\factory\autoflow_resident.py") --detach --interval 30
for ($i = 0; $i -lt 40; $i++) { Start-Sleep -Milliseconds 500; if ((Test-Path $Hb) -and ((Get-Item $Hb).LastWriteTime -gt $t0)) { Write-Host "autoflow_resident up"; exit 0 } }
Write-Host "autoflow_resident 没有写心跳"; exit 1
