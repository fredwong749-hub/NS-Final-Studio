# 笔记本开机自启（封板 P0-7，fredw-92）

登录后自动拉起：画布 API :8800、前端 :5173、gpu3 隧道（15180 桥 / 18098 Qwen / 18099 信箱）；
同步脚本（ops/sync/，单次运行 + 锁）由计划任务定时调。**注册计划任务属于持久化操作，由项目方本人执行**（PowerShell，普通权限即可）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\NS-Final Studio\ops\autostart\register_owner.ps1"
```

register_owner.ps1 依次：删掉指向不存在路径的旧任务 NS-Studio-Autostart-Trial；注册登录自启 NS-Studio-Laptop-Autostart（API + 前端 + 隧道）；
注册 5 个同步任务 NSFS-sync_laptop / NSFS-mirror_prune（每 10 分钟）、NSFS-pull_laptop / NSFS-previews_sync / NSFS-music_sync（每 15 分钟）；
立即跑一次自启并列出已注册任务。
（封板修复：原先这里抄的 schtasks 命令用 `\"` 转义，在 PowerShell 里不生效，路径带空格会注册坏；请只用 register_owner.ps1，它用的是 PowerShell 的反引号转义。）

撤销：`schtasks /Delete /TN <任务名> /F`。日志：`ops\logs\*.log`（autostart.log、tunnel.log、sync_laptop.log …）。
ops/_old_laptop_copy_20261030/ 是分叉的旧拷贝，不要用（现行版是 ops/sync/）。
