# 注册计划任务 NS-Studio-Monitor-Guard（L-106 项目方 11-02 03:2x 授权“允许笔记本监控自启”）：当前用户登录时启动 monitor_guard.ps1；
# 任务失败每 1 分钟重启（最多 999 次），不限运行时长，电池也运行。撤销：Unregister-ScheduledTask -TaskName NS-Studio-Monitor-Guard -Confirm:$false
$name = "NS-Studio-Monitor-Guard"
$act = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"D:\NS-Final Studio\ops\autostart\monitor_guard.ps1`""
# SELF-HEAL 11-05：登录触发之外再加“每 5 分钟重复”触发——守护进程万一没了（被杀 / 登录触发没赶上），最多 5 分钟内计划任务重新拉起；MultipleInstances IgnoreNew + 脚本里的命名互斥体保证不会起两份
$trg = @((New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME), (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)))
$set = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
$prn = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $act -Trigger $trg -Settings $set -Principal $prn -Description "NS-Final Studio 笔记本监控自启（SENTINEL + 8810 看板），L-106" -Force | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State
