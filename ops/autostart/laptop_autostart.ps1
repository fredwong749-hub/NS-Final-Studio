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
$TunnelDown = @(15180, 18098, 18099, 18188, 18191) | Where-Object { -not (Test-Port $_) }
if ($TunnelDown) {
  Start-Process -WindowStyle Hidden -FilePath $Bash -ArgumentList "`"$Root/ops/autostart/tunnel.sh`""
  Log "tunnel started (not listening: $($TunnelDown -join ','))"
} else { Log "tunnel already up" }

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
