# 注册计划任务 NS-Studio-ResidentSync-Guard（WORKFLOW K-OPS-W22；需项目方本人运行或放行）：当前用户登录时启动 resident_guard.ps1；
# 任务失败每 1 分钟重启（最多 999 次），不限运行时长，电池也运行。撤销：Unregister-ScheduledTask -TaskName NS-Studio-ResidentSync-Guard -Confirm:$false
$name = "NS-Studio-ResidentSync-Guard"
$act = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"D:\NS-Final Studio\ops\autostart\resident_guard.ps1`""
$trg = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$set = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
$prn = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $act -Trigger $trg -Settings $set -Principal $prn -Description "NS-Final Studio 笔记本 resident_sync loop 守护（编排器每拍 / 重启队列 / 控制文件推送），K-OPS-W22" -Force | Out-Null
Start-ScheduledTask -TaskName $name
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State
