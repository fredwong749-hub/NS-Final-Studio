# 总调度用：重启 :8800 ns_api，并写重启标记 data/qa/api_restart.json（UIAUDIT / PAGEWATCH 轮询它测冷启动）
# 只在 /api/jobs 没有 queued/running 时重启；-Force 跳过检查。
# 22:0x 总调度（今晚三次自动重启把 :8800 弄挂）：先在备用端口起新代码、确认能起再停旧的；任何一步失败都写 restart_failed + 开告警
#   退出码：0 成功（或补起时 API 已被别人拉起，没动它）/ 1 忙 / 2 旧的已停但端口一直被占 / 3 新进程没起来 / 4 预检失败（旧进程保留）/ 5 别人正在重启（锁被占，什么都没做）
# RESTARTFIX-S（OVERSIGHT 第 16 轮）：全程持有互斥锁 data/ops/api_restart.lock（带 pid；持有者进程没了 / 超 20 分钟可接管）——手动、守护、补起共用；
#   -Revive（守护补起用，与 -Force 同用）：停旧进程之前再测一次 :Port 健康探针，已经健康就 exit 0，绝不停掉一个健康的 API；
#   8801 预检进程树放 try/finally 里清（只清自己起的 pid，pid 也记在 data/ops/api_preflight.pid，脚本被硬杀后下一次启动先清残留）；
#   -UpWaitS 默认 180（冷启动慢，90 秒偏紧）
# RESTARTFIX-O（OVERSIGHT 第 17 轮 P1-1）：
#   · 停旧 = 整棵进程树 taskkill /T /F（API 起的 wsl/ssh 等子进程也停），只停“本脚本记下的”：
#     data/ops/api_<Port>.pid.json（本脚本起看门狗时记 pid + 创建时间）；没有记录（旧版脚本起的）才按“命令行声明 --port <Port>”认，
#     并向上收到 api_watchdog.py 那一层；停之前把整棵树（pid + 创建时间）写进 data/ops/api_<Port>.killed.json；
#   · 端口残留：没有旧进程、看不到属主、端口仍在听，且是 -Revive 或 30 分钟内本脚本停过旧进程（killed.json）→ 按“残留”处理：
#     只补停 killed.json 里还活着的（创建时间对得上），再等 FreeWaitS；不再当 port_foreign 直接退出；
#   · FreeWaitS 默认 240（实测残留 90 s～3 min）；-Revive 时脚本开始之后才出现的实例（别人刚手起的）不当旧进程，等它健康
# 后几个参数只给测试用（tests/test_restart_api_ps1.py 用假端口 / 假 app / 临时目录跑，不碰真 :8800）；生产一律用默认值
param([switch]$Force, [switch]$Revive, [string]$By = "", [string]$Lock = "",
      [int]$Port = 8800, [int]$PrePort = 8801, [string]$App = "ns_api.app:app",
      [string]$KillMatch = "uvicorn ns_api.app:app", [string]$DataDir = "", [string]$LogDir = "",
      [int]$PreWaitS = 60, [int]$FreeWaitS = 240, [int]$UpWaitS = 180, [string]$Probe = "/api/season", [string]$AppDir = "")
$ScriptStart = Get-Date
$Root = "D:\NS-Final Studio"
if (-not $DataDir) { $DataDir = Join-Path $Root "data" }
if (-not $LogDir) { $LogDir = Join-Path $Root "ops\logs" }
$AppArgs = @(); if ($AppDir) { $AppArgs = @("--app-dir", $AppDir) }
# 总调度 20:5x：记下调用方（agent 名 / 父进程链 / 命令行）→ data/ops/restart_events.jsonl；不写 -By 也会记父进程链
$OpsDir = Join-Path $DataDir "ops"
New-Item -ItemType Directory -Force -Path $OpsDir, (Join-Path $DataDir "qa"), $LogDir | Out-Null
$Events = Join-Path $OpsDir "restart_events.jsonl"
$chain = @(); $cur = $PID
for ($i = 0; $i -lt 6 -and $cur; $i++) {
    $pp = Get-CimInstance Win32_Process -Filter "ProcessId=$cur" -ErrorAction SilentlyContinue
    if (-not $pp) { break }
    $c = [string]$pp.CommandLine
    $chain += @{ pid = $pp.ProcessId; name = $pp.Name; cmd = $c.Substring(0, [Math]::Min(200, $c.Length)) }
    $cur = $pp.ParentProcessId
}
$ev = @{ at = (Get-Date).ToString("s"); event = "restart_requested"; by = $(if ($By) { $By } else { "unknown（没写 -By）" }); force = [bool]$Force; parent_chain = $chain }
($ev | ConvertTo-Json -Depth 4 -Compress) | Add-Content -Path $Events -Encoding utf8
$Marker = Join-Path $DataDir "qa\api_restart.json"
if (-not $Lock) { $Lock = Join-Path $OpsDir "api_restart.lock" }
$PrePidFile = Join-Path $OpsDir "api_preflight.pid"
$ApiPidFile = Join-Path $OpsDir "api_$Port.pid.json"        # 本脚本起的看门狗（树根）pid + 创建时间
$KilledFile = Join-Path $OpsDir "api_$Port.killed.json"     # 最近一次停掉的整棵树（pid + 创建时间），残留补停只认它
$script:PreStarted = $null
$script:haveLock = $false
$script:LockStream = $null

function Event([hashtable]$H) {
    $H["at"] = (Get-Date).ToString("s"); if (-not $H.ContainsKey("by")) { $H["by"] = $By }
    ($H | ConvertTo-Json -Depth 5 -Compress) | Add-Content -Path $Events -Encoding utf8
}
# ---- 进程身份 = pid + 创建时间（防 pid 复用）
function Proc-All() { return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue) }
function Born($P) { try { return [string]([datetime]$P.CreationDate).ToUniversalTime().Ticks } catch { return "" } }
function Find-Proc($All, [int]$Id) { return ($All | Where-Object { [int]$_.ProcessId -eq $Id } | Select-Object -First 1) }
function Same-Proc($All, [int]$Id, [string]$B) { $p = Find-Proc $All $Id; return [bool]($p -and $B -and (Born $p) -eq $B) }
# 根 + 全部后代（子进程创建时间不早于父进程，防 pid 复用把无关进程接进来）
function Tree-Of($All, [int[]]$Roots) {
    # 键用字符串：[ordered] 字典的 [int] 下标是“按位置”取值，不是按键
    $seen = @{}; $out = New-Object System.Collections.ArrayList; $q = New-Object System.Collections.Queue
    foreach ($r in $Roots) { $p = Find-Proc $All $r; if ($p -and -not $seen.ContainsKey("$r")) { $seen["$r"] = 1; [void]$out.Add($p); $q.Enqueue($p) } }
    while ($q.Count) {
        $p = $q.Dequeue(); $pb = [datetime]$p.CreationDate
        foreach ($c in @($All | Where-Object { [int]$_.ParentProcessId -eq [int]$p.ProcessId -and [int]$_.ProcessId -ne [int]$p.ProcessId })) {
            $k = "$([int]$c.ProcessId)"
            if (-not $seen.ContainsKey($k) -and ([datetime]$c.CreationDate) -ge $pb) { $seen[$k] = 1; [void]$out.Add($c); $q.Enqueue($c) }
        }
    }
    return @($out)
}
# 逐个强停（整棵树已由 Tree-Of 按“pid + 创建时间”收好）
function Stop-Ids([int[]]$Ids) {
    foreach ($id in $Ids) { & taskkill.exe /PID $id /F 2>&1 | Out-Null }
    foreach ($id in $Ids) { try { Stop-Process -Id $id -Force -Confirm:$false -ErrorAction Stop } catch {} }
}
# 只停记录里的进程（创建时间对得上），以及它们后来又起的子进程；返回 1 秒后仍活着的 pid
function Kill-Recorded($Rec) {
    $all = Proc-All
    $live = @($Rec | Where-Object { Same-Proc $all ([int]$_.pid) ([string]$_.born) })
    $liveIds = @($live | ForEach-Object { [int]$_.pid })
    # ISS-1103-014614-9db2(1)：后代一律走 Tree-Of（子进程创建时间不早于父进程），不用 taskkill /T（/T 只按 ParentProcessId 认，
    # 会把“父 pid 恰好被复用”的无关老进程也算进来）
    $ids = @(Tree-Of $all $liveIds | ForEach-Object { [int]$_.ProcessId })
    Stop-Ids $ids
    Start-Sleep -Milliseconds 1000
    $all = Proc-All
    return @($Rec | Where-Object { Same-Proc $all ([int]$_.pid) ([string]$_.born) } | ForEach-Object { [int]$_.pid })
}
function Read-Killed([int]$MaxMin) {
    try {
        $k = (Get-Content $KilledFile -Raw -ErrorAction Stop) | ConvertFrom-Json
        if (((Get-Date) - (Get-Item $KilledFile).LastWriteTime).TotalMinutes -le $MaxMin) { return $k }
    } catch {}
    return $null
}
# 停整棵树：先写 killed.json（脚本被中途杀也留得下要补停的名单），再逐个强停树上每个进程（Tree-Of 核过创建时间），再补停链断后的孤儿
function Stop-Tree($All, [int[]]$Roots, [string]$Source) {
    $tree = Tree-Of $All $Roots
    $rec = @($tree | ForEach-Object { [ordered]@{ pid = [int]$_.ProcessId; born = (Born $_); parent = [int]$_.ParentProcessId; name = [string]$_.Name } })
    ([ordered]@{ at = (Get-Date).ToString("s"); port = $Port; source = $Source; roots = $Roots; pids = $rec } | ConvertTo-Json -Depth 5) |
        Set-Content -Path $KilledFile -Encoding utf8
    Event @{ event = "stopping_old"; source = $Source; roots = $Roots; pids = @($rec | ForEach-Object { "$($_.pid):$($_.name)" }) }
    Stop-Ids @($rec | ForEach-Object { [int]$_.pid })
    return (Kill-Recorded $rec)
}

function Fail-Restart([string]$Stage, [string]$Why, [int]$Code, [bool]$OldKept) {
    $now = Get-Date
    (@{ at = $now.ToString("s"); event = "restart_failed"; stage = $Stage; why = $Why; by = $By; old_kept = $OldKept } | ConvertTo-Json -Compress) |
        Add-Content -Path $Events -Encoding utf8
    $msg = $(if ($OldKept) { ":$Port 重启没做（$Stage）：$Why；旧进程保留在跑" } else { ":$Port 重启失败（$Stage）：$Why；旧进程已停、新进程没起来，API 现在不在" })
    $epoch = [double]([DateTimeOffset]$now).ToUnixTimeMilliseconds() / 1000
    (@{ ts = $now.ToString("s"); t = $epoch; id = "A-API-RESTART-FAIL"; state = "open"; level = $(if ($OldKept) { "warn" } else { "crit" }); msg = $msg; by = "restart_api.ps1" } | ConvertTo-Json -Compress) |
        Add-Content -Path (Join-Path $DataDir "qa\alerts.jsonl") -Encoding utf8
    Write-Host $msg
    exit $Code
}
function Tail-Of([string]$File, [int]$Max) {
    $t = ""
    try { $t = ((Get-Content $File -Tail 3 -ErrorAction Stop) -join " | ") } catch {}
    return $t.Substring(0, [Math]::Min($Max, $t.Length))
}
# 端口是否被占：netstat 视图 / 能连上 / 绑不上，任一成立就算占（受限环境里 Get-NetTCPConnection 可能看不到别的进程，21:58 还见过属主 PID 0 的残留监听）
# RESTARTFIX-O：快的先测（绑不上 / 连得上 → 立即算占），Get-NetTCPConnection 本机一次约 3.8 s，放最后（只在前两项都说“空”时才查）
function Listening([int]$P) {
    try { $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $P); $l.Start(); $l.Stop() } catch { return $true }
    try { $c = [System.Net.Sockets.TcpClient]::new(); $ok = $c.ConnectAsync("127.0.0.1", $P).Wait(500); $c.Dispose(); if ($ok) { return $true } } catch {}
    if (Get-NetTCPConnection -LocalPort $P -State Listen -ErrorAction SilentlyContinue) { return $true }
    return $false
}

# ---- 互斥锁：CreateNew 原子创建，并且整个重启期间一直开着文件句柄（不给删除共享）——持有者活着时别人删不掉、改不了名；
#      持有者进程一死，句柄由系统关掉，锁才可能被接管（RESTARTFIX-O P2-2：两个接管者不会都成功；pid 复用不会白等）
# 已存在且删不掉 → 别人在重启；删得掉但内容里 pid 活着、创建时间对得上（或旧格式无创建时间）且 < 20 分钟 → 也当别人在重启
function Lock-Holder-Alive() {
    try {
        $age = ((Get-Date) - (Get-Item $Lock -ErrorAction Stop).LastWriteTime).TotalMinutes
        $o = (Get-Content $Lock -Raw -ErrorAction Stop) | ConvertFrom-Json
        if ($age -gt 20) { return $false }
        if ([int]$o.pid -eq $PID) { return $false }
        $all = Proc-All; $p = Find-Proc $all ([int]$o.pid)
        if (-not $p) { return $false }
        if ($o.born) { return ((Born $p) -eq [string]$o.born) }
        return $true
    } catch {
        # 读不出来：刚创建还没写完（<5 秒）当占着，否则当残留
        try { return (((Get-Date) - (Get-Item $Lock -ErrorAction Stop).LastWriteTime).TotalSeconds -lt 5) } catch { return $false }
    }
}
function Acquire-Lock() {
    $me = Find-Proc (Proc-All) $PID
    for ($n = 0; $n -lt 3; $n++) {
        try {
            $fs = [System.IO.File]::Open($Lock, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
            $b = [System.Text.Encoding]::UTF8.GetBytes((@{ pid = $PID; born = (Born $me); at = (Get-Date).ToString("s"); by = $By } | ConvertTo-Json -Compress))
            $fs.Write($b, 0, $b.Length); $fs.Flush()
            $script:LockStream = $fs        # 不关：持有到 Release-Lock
            return $true
        } catch {
            if (-not (Test-Path $Lock)) { continue }
            if (Lock-Holder-Alive) { return $false }
            # 删得掉 = 没有活着的持有者开着句柄；删不掉（句柄被占）= 别人刚接管 / 正在重启
            try { Remove-Item $Lock -Force -ErrorAction Stop } catch { if (Test-Path $Lock) { return $false } }
        }
    }
    return $false
}
function Release-Lock() {
    if (-not $script:haveLock) { return }
    try { if ($script:LockStream) { $script:LockStream.Dispose() } } catch {}
    $script:LockStream = $null
    try { if ((((Get-Content $Lock -Raw -ErrorAction Stop) | ConvertFrom-Json).pid) -eq $PID) { Remove-Item $Lock -Force -ErrorAction SilentlyContinue } } catch {}
    $script:haveLock = $false
}
# 只清自己起的预检进程树（pid 在 $script:PreStarted / pid 文件里）
function Stop-Preflight([int]$ProcId) {
    if ($ProcId -gt 0) { & taskkill.exe /PID $ProcId /T /F 2>&1 | Out-Null }
    Remove-Item $PrePidFile -Force -ErrorAction SilentlyContinue
}
if (-not (Acquire-Lock)) {
    (@{ at = (Get-Date).ToString("s"); event = "restart_skipped"; stage = "lock_busy"; why = "别人正在重启（锁 $Lock 被占）"; by = $By } | ConvertTo-Json -Compress) | Add-Content -Path $Events -Encoding utf8
    Write-Host "别人正在重启（锁被占），本次不动"
    exit 5
}
$script:haveLock = $true

function Api-Healthy() {
    try { return ((Invoke-WebRequest "http://127.0.0.1:$Port$Probe" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) } catch { return $false }
}
function Skip-Healthy([string]$Where) {
    (@{ at = (Get-Date).ToString("s"); event = "restart_skipped"; stage = "already_healthy"; why = "补起前（$Where）:$Port 已经健康，没动它"; by = $By } | ConvertTo-Json -Compress) | Add-Content -Path $Events -Encoding utf8
    Write-Host ":$Port 已经健康（$Where），补起不需要，没动它"
    exit 0
}

try {
# 上次被硬杀留下的预检进程（pid 文件里记的、命令行确实是 --port $PrePort）先清掉
if (Test-Path $PrePidFile) {
    try {
        $lp = [int](Get-Content $PrePidFile -Raw).Trim()
        $lc = Get-CimInstance Win32_Process -Filter "ProcessId=$lp" -ErrorAction SilentlyContinue
        if ($lc -and ([string]$lc.CommandLine) -match ("--port\s+" + $PrePort + "(\D|$)")) { Stop-Preflight $lp }
    } catch {}
    Remove-Item $PrePidFile -Force -ErrorAction SilentlyContinue
}
if ($Revive -and (Api-Healthy)) { Skip-Healthy "拿到锁后" }

if (-not $Force) {
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$Port/api/jobs" -TimeoutSec 10
        $j = if ($r.jobs) { $r.jobs } else { $r }
        $busy = @($j | Where-Object { $_.state -in 'queued', 'running' }).Count
        if ($busy -gt 0) { Write-Host "busy $busy，不重启"; exit 1 }
    } catch { Write-Host "读 /api/jobs 失败，按未运行处理" }
}

# 1) 先起新的、确认能起再切换：新代码在备用端口完整起一份 uvicorn，探针 200 才去停旧进程；
#    起不来 → 不杀旧进程（回退 = 保留旧进程）。备用实例只停我们自己记下的 pid 树（K-OPS-F30）
if (Listening $PrePort) { Fail-Restart "preflight_port" "备用端口 $PrePort 被占，没法先验新代码" 4 $true }
$env:NS_API_PREFLIGHT = "1"      # app._lifecycle 看到它不记 api_startup / api_shutdown（预检实例不是真服务）
$env:NS_POSTFLIGHT_SWEEP = "0"   # RESTARTFIX-O P2-1：预检实例不起 postflight 扫描线程（会写真实 takes.json）；frame_jobs 也认 NS_API_PREFLIGHT
$env:NS_NO_API_SNAPSHOT = "1"    # 预检实例不写摘要快照
$preErr = Join-Path $LogDir "api_preflight.err.log"
$preProc = Start-Process -PassThru -WindowStyle Hidden -WorkingDirectory $Root -FilePath "$Root\.venv\Scripts\python.exe" `
    -ArgumentList (@("-m", "uvicorn", $App, "--port", "$PrePort", "--host", "127.0.0.1") + $AppArgs) `
    -RedirectStandardOutput (Join-Path $LogDir "api_preflight.out.log") -RedirectStandardError $preErr
Remove-Item Env:NS_API_PREFLIGHT, Env:NS_POSTFLIGHT_SWEEP, Env:NS_NO_API_SNAPSHOT -ErrorAction SilentlyContinue
$script:PreStarted = $preProc
try { Set-Content -Path $PrePidFile -Value $preProc.Id -Encoding ascii } catch {}
$preOk = $false; $preBy = (Get-Date).AddSeconds($PreWaitS)
while (-not $preOk -and (Get-Date) -lt $preBy -and -not $preProc.HasExited) {
    try { if ((Invoke-WebRequest "http://127.0.0.1:$PrePort$Probe" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { $preOk = $true } } catch {}
    if (-not $preOk) { Start-Sleep -Milliseconds 500 }
}
Stop-Preflight $preProc.Id
$script:PreStarted = $null
if (-not $preOk) { Fail-Restart "preflight" "新代码在备用端口 $PrePort 起不来：$(Tail-Of $preErr 260)" 4 $true }
$preFreeBy = (Get-Date).AddSeconds(30)
while ((Listening $PrePort) -and (Get-Date) -lt $preFreeBy) { Start-Sleep -Milliseconds 300 }

# 2) 认旧的（只认本脚本记下的）：先看 api_<Port>.pid.json（pid + 创建时间都对得上才算）；
#    没有记录（旧版脚本起的）→ 命令行含 KillMatch 且声明 --port $Port 的 python，再向上收到同端口的 api_watchdog.py（看门狗也要停，整棵树一起）
#    -Revive：脚本开始之后才出现的实例是别人刚手起的，不当旧进程（P2-5）
$all = Proc-All
$roots = @(); $source = ""; $fresh = @()
try {
    $pf = (Get-Content $ApiPidFile -Raw -ErrorAction Stop) | ConvertFrom-Json
    if ([int]$pf.port -eq $Port -and (Same-Proc $all ([int]$pf.pid) ([string]$pf.born))) { $roots = @([int]$pf.pid); $source = "pid_file" }
} catch {}
$portRe = "--port\s+" + $Port + "(\D|$)"
if (-not $roots.Count) {
    $claim = @($all | Where-Object { $_.Name -eq "python.exe" -and ([string]$_.CommandLine) -match [regex]::Escape($KillMatch) -and ([string]$_.CommandLine) -match $portRe })
    if ($Revive) {
        $fresh = @($claim | Where-Object { ([datetime]$_.CreationDate) -gt $ScriptStart })
        $claim = @($claim | Where-Object { ([datetime]$_.CreationDate) -le $ScriptStart })
    }
    foreach ($c in $claim) {
        $top = $c
        for ($i = 0; $i -lt 6; $i++) {
            $par = Find-Proc $all ([int]$top.ParentProcessId)
            if ($par -and ([string]$par.CommandLine) -match "api_watchdog\.py" -and ([string]$par.CommandLine) -match $portRe -and
                ([datetime]$par.CreationDate) -le ([datetime]$top.CreationDate)) { $top = $par } else { break }
        }
        if ($roots -notcontains [int]$top.ProcessId) { $roots += [int]$top.ProcessId }
    }
    if ($roots.Count) { $source = "claim" }
}
$oldIds = @(Tree-Of $all $roots | ForEach-Object { [int]$_.ProcessId })

# 先核端口：看得到的监听者里有不是旧进程树的（别的程序占着），新进程拿不到端口 → 一个都不杀，保留旧进程
$owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.OwningProcess } | Where-Object { $_ -ne 0 })
$foreign = @($owners | Where-Object { $oldIds -notcontains $_ })
if ($foreign.Count -gt 0) { Fail-Restart "port_foreign" "$Port 端口被别的进程占着（$($foreign -join ',')），新进程拿不到端口" 4 $true }
# ISS-1103-014614-9db2(2)：受限 shell 里 Get-NetTCPConnection 可能一个监听者都看不到 → 再问 :Port/api/_instance（真 ns_api 才有这个接口）；
#   回的 pid 不在旧进程树里 = 端口上服务的不是我们要停的那份 → 一个都不杀（问不到 = 不知道，按原逻辑走）
if ($roots.Count -and -not $owners.Count) {
    try {
        $ii = Invoke-RestMethod "http://127.0.0.1:$Port/api/_instance" -TimeoutSec 3 -ErrorAction Stop
        if ($ii.pid -and $oldIds -notcontains [int]$ii.pid) {
            Fail-Restart "port_foreign" "$Port 上服务的是 pid $($ii.pid)，不在要停的旧进程树（$($oldIds -join ',')）里，新进程拿不到端口" 4 $true
        }
    } catch {}
}
if ($Revive -and $fresh.Count) {
    # 别人刚手起的实例（P2-5）：不杀，等它健康
    $fb = (Get-Date).AddSeconds($UpWaitS)
    while ((Get-Date) -lt $fb) { if (Api-Healthy) { Skip-Healthy "别人刚起的实例 $(@($fresh | ForEach-Object { $_.ProcessId }) -join ',') 已健康" }; Start-Sleep -Milliseconds 1000 }
    Fail-Restart "someone_starting" "补起期间别人起了实例 $(@($fresh | ForEach-Object { $_.ProcessId }) -join ',')，$UpWaitS 秒没健康；没动它" 4 $true
}
# 没有旧进程、看不到属主、端口仍在听：
#   -Revive 或 30 分钟内本脚本停过旧进程 → 端口残留（11-02 21:58 / 00:09 实测 90 s～3 min），补停记录里还活着的、等 FreeWaitS；
#   否则仍按“别的程序占着”保留现状（port_foreign）
$residual = $false
if (-not $roots.Count -and (Listening $Port)) {
    $kr = Read-Killed 30
    if ($Revive -or $kr) { $residual = $true }
    else { Fail-Restart "port_foreign" "$Port 端口被占着，属主看不到，且没有旧进程声明这个端口、30 分钟内也没停过旧进程，新进程拿不到端口" 4 $true }
}
if ($Revive -and (Api-Healthy)) { Skip-Healthy "停旧进程之前" }   # 预检要几十秒，这期间可能已被别人拉起
$stopped = (Get-Date).ToString("s")
if ($residual) {
    $left = @(); if ($kr) { $left = @(Kill-Recorded $kr.pids) }
    Event @{ event = "port_residual"; recorded = [bool]$kr; still_alive = $left; listen = (Listening $Port) }
} elseif ($roots.Count) {
    $left = @(Stop-Tree $all $roots $source)
    Event @{ event = "old_stopped"; source = $source; still_alive = $left; listen_after_1s = (Listening $Port) }   # 诊断：杀完立刻还在听 = 残留
}
$stopT = Get-Date      # port_freed_s = 停完之后端口还要等多久才空（0 附近 = 没有残留）

# 3) 守卫（总调度 19:3x，V2-WALK W-12）：确认端口空了才起新的，不叠第二份。
#    旧进程死后监听套接字可能还挂着（11-02 21:58 / 11-03 00:09 实测 90 s～3 min）→ 等 FreeWaitS（默认 240）；仍占着 = 失败 + 告警
# 注：.venv\Scripts\python.exe 在 Windows 上是转发器，会再起一个系统 Python 子进程——父子两个算同一份服务，不是重复
$freeBy = (Get-Date).AddSeconds($FreeWaitS)
$busyNow = Listening $Port
while ($busyNow -and (Get-Date) -lt $freeBy) { Start-Sleep -Milliseconds 500; $busyNow = Listening $Port }
$freedS = [Math]::Round(((Get-Date) - $stopT).TotalSeconds, 1)
if ($busyNow) {
    $holders = (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess) -join ","
    Fail-Restart $(if ($residual) { "port_residual" } else { "port_busy" }) "$(if ($residual) { '端口残留' } else { '旧进程已结束但' }) $Port 端口 $FreeWaitS 秒仍被占用（进程 $holders）" 2 $false
}

# 4) 起新的（看门狗包一层，记 started / exited）；树根 pid + 创建时间记进 api_<Port>.pid.json，下次只停它这棵树
$env:NS_COMFY_URL = "http://127.0.0.1:18188"
$apiErr = Join-Path $LogDir "api_$Port.err.log"
# RESTARTFIX-O（01:48 受控重启后 P1）：看门狗不再由本脚本直接 Start-Process（带重定向 = 继承本进程全部可继承句柄，含调用方的管道 →
#   调用方等不到 EOF；且挂在调用方会话的作业对象下，会话结束会被整棵带走）。改为 api_watchdog.py --detach：
#   短命的启动器另起一份看门狗（DETACHED_PROCESS + 新进程组 + CREATE_BREAKAWAY_FROM_JOB，只继承日志文件句柄），写 pid 文件后立刻退出
$q = { param($s) '"' + $s + '"' }
$detFile = Join-Path $OpsDir "api_$Port.detach.json"
Remove-Item $detFile -Force -ErrorAction SilentlyContinue
$dArgs = @("tools/factory/api_watchdog.py", "--detach", "--by", (& $q $(if ($By) { $By } else { "restart_api" })),
           "--out", (& $q (Join-Path $LogDir "api_$Port.out.log")), "--err", (& $q $apiErr), "--pidfile", (& $q $detFile),
           "--", "-m", "uvicorn", $App, "--port", "$Port", "--host", "127.0.0.1") + @($AppArgs | ForEach-Object { & $q $_ })
$launcher = Start-Process -PassThru -WindowStyle Hidden -WorkingDirectory $Root -FilePath "$Root\.venv\Scripts\python.exe" -ArgumentList $dArgs `
    -RedirectStandardOutput (Join-Path $LogDir "api_$Port.detach.out.log") -RedirectStandardError (Join-Path $LogDir "api_$Port.detach.err.log")
[void]$launcher.WaitForExit(60000)      # 只等启动器本身（几秒），不等它起的看门狗
$wdPid = 0; $breakaway = $null
try { $dj = (Get-Content $detFile -Raw -ErrorAction Stop) | ConvertFrom-Json; $wdPid = [int]$dj.pid; $breakaway = [bool]$dj.breakaway } catch {}
if (-not $wdPid) { Fail-Restart "detach" "看门狗启动器没写出 pid（$(Tail-Of (Join-Path $LogDir "api_$Port.detach.err.log") 240)）" 3 $false }
Remove-Item $detFile -Force -ErrorAction SilentlyContinue
try {
    $np = Find-Proc (Proc-All) $wdPid
    ([ordered]@{ pid = $wdPid; born = (Born $np); port = $Port; at = (Get-Date).ToString("s"); by = $By; breakaway = $breakaway } | ConvertTo-Json -Compress) | Set-Content -Path $ApiPidFile -Encoding utf8
} catch {}

$up = $null
$upBy = (Get-Date).AddSeconds($UpWaitS)
while (-not $up -and (Get-Date) -lt $upBy) {
    try { if ((Invoke-WebRequest "http://127.0.0.1:$Port$Probe" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { $up = (Get-Date).ToString("s"); break } } catch {}
    Start-Sleep -Milliseconds 500
}
if (-not $up) { Fail-Restart "not_up" "新进程 $UpWaitS 秒内 $Probe 没有 200：$(Tail-Of $apiErr 240)" 3 $false }
@{ stopped_at = $stopped; up_at = $up; by = $(if ($By) { $By } else { "unknown（没写 -By）" }) } | ConvertTo-Json | Set-Content -Path $Marker -Encoding utf8
Event @{ event = "restart_done"; up_at = $up; port_freed_s = $freedS; old_source = $source; residual = $residual }
Remove-Item $KilledFile -Force -ErrorAction SilentlyContinue      # 成功起来：残留名单作废（只给“停旧后没起来”的补起用）
Write-Host "stopped $stopped  up $up"
} finally {
    if ($script:PreStarted) { Stop-Preflight $script:PreStarted.Id }   # 被中断（Ctrl-C / exit）时也清预检进程树
    Release-Lock
}
