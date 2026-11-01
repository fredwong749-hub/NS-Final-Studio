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

# 1) NETFIX 11-01（K-OPS-N01）：全部端口转发（gpu33 六条 + gpu36 三条）由监管进程 tools/netfix/tunnel_supervisor.py 一家负责
#    （每台服务器一条 ssh、指数退避、卡死检测、跳板恢复 60 s 内全部恢复、接管孤儿 ssh）。ensure = 不在就后台拉起，在就跳过。
#    旧的 tunnel.sh / tunnel_gpu36.sh 循环已退役（调用它们也只会转去 ensure）。监管进程自身另有计划任务 NS-Studio-TunnelSupervisor 每 5 分钟 ensure。
$env:PYTHONUTF8 = "1"
$SupOut = & (Join-Path $Root ".venv\Scripts\python.exe") (Join-Path $Root "tools\netfix\tunnel_supervisor.py") ensure 2>&1
Log "tunnel_supervisor ensure: $SupOut"

# 1c) WORKFLOW 11-01（NIGHT_PLAN W7，K-OPS-W05/W06）：基础设施看门狗——30 s 探测 6 条渲染道隧道并报警；监管进程在岗时不修（NETFIX K-OPS-N01），监管进程心跳过期才兜底杀 ssh；
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
