# 注册计划任务 NS-Studio-Monitor-Guard（L-106 项目方 11-02 03:2x 授权“允许笔记本监控自启”）：当前用户登录时启动 monitor_guard.ps1；
# 任务失败每 1 分钟重启（最多 999 次），不限运行时长，电池也运行。撤销：Unregister-ScheduledTask -TaskName NS-Studio-Monitor-Guard -Confirm:$false
$name = "NS-Studio-Monitor-Guard"
$act = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"D:\NS-Final Studio\ops\autostart\monitor_guard.ps1`""
$trg = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$set = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
$prn = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $act -Trigger $trg -Settings $set -Principal $prn -Description "NS-Final Studio 笔记本监控自启（SENTINEL + 8810 看板），L-106" -Force | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State
