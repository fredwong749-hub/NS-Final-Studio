# 笔记本开机（登录）自启：画布 API :8800、前端 :5173、gpu3 隧道。已在运行的跳过。日志在 ops\logs\。
# 由计划任务 NS-Studio-Laptop-Autostart（登录时）调用；注册命令见 ops\autostart\README.md（项目方本人执行）。
$ErrorActionPreference = "Continue"
$Root = "D:\NS-Final Studio"
$Logs = Join-Path $Root "ops\logs"
New-Item -ItemType Directory -Force $Logs | Out-Null
$Bash = "C:\Program Files\Git\bin\bash.exe"

function Test-Port([int]$Port) {
  try { $c = [System.Net.Sockets.TcpClient]::new("127.0.0.1", $Port); $c.Close(); return $true } catch { return $false }
}
function Log([string]$Msg) { Add-Content -Path (Join-Path $Logs "autostart.log") -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg" -Encoding UTF8 }

# 1) gpu3 隧道（15180 / 18098 / 18099）—— 自带锁，重复启动会自己退出
# 封板修复：三个端口任一不在监听就拉起隧道（原先只看 15180，18098 Qwen / 18099 信箱掉了永远不会补）
$TunnelDown = @(15180, 18098, 18099, 18188, 18189, 18191) | Where-Object { -not (Test-Port $_) }
if ($TunnelDown) {
  Start-Process -WindowStyle Hidden -FilePath $Bash -ArgumentList "`"$Root/ops/autostart/tunnel.sh`""
  Log "tunnel started (not listening: $($TunnelDown -join ','))"
} else { Log "tunnel already up" }

# 1b) fredw-92/G36：gpu36 渲染道隧道（18288 → gpu36:0 / 18289 → gpu36:1 / 18290 → gpu36:2）——自带锁
$G36Down = @(18288, 18289, 18290) | Where-Object { -not (Test-Port $_) }
if ($G36Down) {
  Start-Process -WindowStyle Hidden -FilePath $Bash -ArgumentList "`"$Root/ops/autostart/tunnel_gpu36.sh`""
  Log "tunnel_gpu36 started (not listening: $($G36Down -join ','))"
} else { Log "tunnel_gpu36 already up" }

# 1c) WORKFLOW 11-01（NIGHT_PLAN W7，K-OPS-W05/W06）：基础设施看门狗——30 s 探测 6 条渲染道隧道，卡死就杀 ssh 让上面两个循环重连；
#     空转 / night 卡住 / producer 心跳过期写 data\qa\alerts.jsonl（看板 :8810 显示）。serve 自己查 pid 防重复。
$env:PYTHONUTF8 = "1"
Start-Process -WindowStyle Hidden -WorkingDirectory $Root -FilePath (Join-Path $Root ".venv\Scripts\python.exe") `
  -ArgumentList "-u", "tools/autopilot/infra_watchdog.py", "serve" `
  -RedirectStandardOutput (Join-Path $Logs "infra_watchdog.out.log") -RedirectStandardError (Join-Path $Logs "infra_watchdog.err.log")
Log "infra_watchdog ensured"

# 2) 画布 API :8800
if (-not (Test-Port 8800)) {
  # 出图默认走 gpu3 GPU0 ComfyUI（隧道 18188）；视频 / 按卡选择见 config\render_endpoints.json（W2）
  $env:NS_COMFY_URL = "http://127.0.0.1:18188"
  Start-Process -WindowStyle Hidden -WorkingDirectory $Root -FilePath (Join-Path $Root ".venv\Scripts\python.exe") `
    -ArgumentList "-m", "uvicorn", "ns_api.app:app", "--port", "8800", "--host", "127.0.0.1" `
    -RedirectStandardOutput (Join-Path $Root "data\api_8800.out.log") -RedirectStandardError (Join-Path $Root "data\api_8800.err.log")
  Log "api started"
} else { Log "api already up" }

# 3) 前端 :5173（vite dev）
if (-not (Test-Port 5173)) {
  Start-Process -WindowStyle Hidden -FilePath "cmd.exe" -ArgumentList "/c", "cd /d `"$Root\apps\web`" && npm run dev >> `"$Logs\web_dev.log`" 2>&1"
  Log "web started"
} else { Log "web already up" }

# 4) PRODUCER 制作监督（总调度 11-01，项目方选方案 A：常驻、自动推进、人类只处理闸门；规则 K-OPS-A01）
#    已在跑（data\producer\producer.pid 的进程还活着）就跳过；serve 自己也会查 pid 防重复。暂停 = data\producer\control.json paused。
$ProdPid = Join-Path $Root "data\producer\producer.pid"
$ProdAlive = $false
if (Test-Path $ProdPid) {
  try { $pp = (Get-Content $ProdPid -Raw | ConvertFrom-Json).pid; if ($pp -and (Get-Process -Id $pp -ErrorAction SilentlyContinue)) { $ProdAlive = $true } } catch { }
}
if (-not $ProdAlive) {
  $env:PYTHONUTF8 = "1"
  Start-Process -WindowStyle Hidden -WorkingDirectory $Root -FilePath (Join-Path $Root ".venv\Scripts\python.exe") `
    -ArgumentList "-u", "tools/autopilot/producer.py", "serve" `
    -RedirectStandardOutput (Join-Path $Logs "producer.out.log") -RedirectStandardError (Join-Path $Logs "producer.err.log")
  Log "producer started"
} else { Log "producer already up" }
