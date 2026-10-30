<#
渲染成人镜头（由项目方本人启动）。

用法（任选其一）:
  - 双击 tools\run_adult_batch.cmd
  - pwsh -File tools\run_adult_batch.ps1                 # 出首帧
  - pwsh -File tools\run_adult_batch.ps1 -Stage last     # 出尾帧（需要已有首帧）
  - pwsh -File tools\run_adult_batch.ps1 -Shots ep05,ep09

视频只在 gpu3 渲染一次（项目方 2026-10-30，docs/TASKS.md 规则 7）：本机不出视频，
gpu3 会用这里出好的当前首帧/尾帧去出视频。

流程: 等其它 render_batch 进程结束、ComfyUI 队列清空 → 带 --include-adult 运行 render_batch
      （已有当前版本的镜头会跳过，可以随时中断再续跑）→ 重写 data\renders\REPORT.md。
日志: data\logs\adult_batch_<时间>.log

想让它每天凌晨自动跑，自己执行一次（以后 schtasks /delete /tn NS-AdultBatch 取消）:
  schtasks /create /tn NS-AdultBatch /sc daily /st 02:00 /tr "pwsh -NoProfile -File \"D:\NS-Final Studio\tools\run_adult_batch.ps1\""
#>
param(
    [ValidateSet("image", "last", "both")] [string]$Stage = "image",   # both = 首帧 + 尾帧（不含视频）
    [string[]]$Shots = @(),
    [string]$Comfy = "http://127.0.0.1:8188"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$env:PYTHONUTF8 = "1"
$Log = Join-Path $Root ("data\logs\adult_batch_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmm"))
New-Item -ItemType Directory -Force (Split-Path $Log) | Out-Null

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $Log -Value $line -Encoding utf8
}

function Test-Busy {
    $others = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -like "*render_batch.py*" -and $_.ProcessId -ne $PID }
    if ($others) { return "其它 render_batch 进程在运行" }
    try {
        $q = Invoke-RestMethod -Uri "$Comfy/queue" -TimeoutSec 10
        if ($q.queue_running.Count -gt 0 -or $q.queue_pending.Count -gt 0) { return "ComfyUI 队列非空" }
    } catch {
        return "ComfyUI 没有响应（$Comfy）"
    }
    return $null
}

# 一镜一条链：项目由 gpu3 负责时直接退出（config/shot_ownership.json）
Push-Location $Root
$gate = & uv run python -c "import sys; sys.stdout.reconfigure(encoding='utf-8'); from ns_render import pipeline as P; m = P.project_gate_message(); print(m or ''); sys.exit(3 if m else 0)"
$gateCode = $LASTEXITCODE
Pop-Location
if ($gateCode -eq 3) {
    Write-Log "$gate：本机不出首尾帧，已退出"
    exit 3
}

Write-Log "等待 GPU 空闲…"
while ($reason = Test-Busy) {
    Write-Log "  $reason，5 分钟后再看"
    Start-Sleep -Seconds 300
}

$stages = if ($Stage -eq "both") { @("image", "last") } else { @($Stage) }   # 不含 video：视频只在 gpu3 出
Push-Location $Root
try {
    foreach ($s in $stages) {
        $argsList = @("run", "python", "tools/render_batch.py", "--stage", $s, "--include-adult", "--comfy", $Comfy)
        if ($Shots.Count -gt 0) { $argsList += @("--shots") + $Shots }
        Write-Log "开始: uv $($argsList -join ' ')"
        & uv @argsList 2>&1 | Tee-Object -FilePath $Log -Append
        Write-Log "阶段 $s 结束（退出码 $LASTEXITCODE）"
    }
    & uv run python tools/render_batch.py --report 2>&1 | Tee-Object -FilePath $Log -Append
} finally {
    Pop-Location
}
Write-Log "全部完成。报告: data\renders\REPORT.md"
