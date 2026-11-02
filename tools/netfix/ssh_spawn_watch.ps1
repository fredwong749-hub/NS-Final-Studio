# NETFIX：统计笔记本上新起的 ssh / scp / sftp 进程（谁在新建到跳板的连接）。每秒采一次，新 pid 记一行 JSON。
# 用法：powershell -NoProfile -File tools/netfix/ssh_spawn_watch.ps1 -Minutes 10 -Out data/netfix/ssh_spawns.jsonl
param([int]$Minutes = 10, [string]$Out = "D:\NS-Final Studio\data\netfix\ssh_spawns.jsonl")
$seen = @{}
Get-CimInstance Win32_Process -Filter "Name='ssh.exe' or Name='scp.exe' or Name='sftp.exe'" | ForEach-Object { $seen[$_.ProcessId] = 1 }
$end = (Get-Date).AddMinutes($Minutes)
while ((Get-Date) -lt $end) {
  $all = Get-CimInstance Win32_Process
  $byId = @{}; foreach ($p in $all) { $byId[$p.ProcessId] = $p }
  foreach ($p in $all) {
    if ($p.Name -notin @('ssh.exe', 'scp.exe', 'sftp.exe')) { continue }
    if ($seen.ContainsKey($p.ProcessId)) { continue }
    $seen[$p.ProcessId] = 1
    $par = $byId[$p.ParentProcessId]; $gp = if ($par) { $byId[$par.ParentProcessId] } else { $null }
    $rec = [ordered]@{ at = (Get-Date -Format s); pid = $p.ProcessId; cmd = $p.CommandLine
                       parent = if ($par) { $par.CommandLine } else { $null }; grand = if ($gp) { $gp.CommandLine } else { $null } }
    Add-Content -Path $Out -Value ($rec | ConvertTo-Json -Compress) -Encoding UTF8
  }
  Start-Sleep -Milliseconds 800
}
