# 笔记本开机自启注册（封板 P0-7）。由项目方本人执行；内容与 README.md 相同。
# 撤销：schtasks /Delete /TN <任务名> /F
schtasks /Delete /TN "NS-Studio-Autostart-Trial" /F 2>$null

schtasks /Create /TN "NS-Studio-Laptop-Autostart" /SC ONLOGON /RL LIMITED /F /TR "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"D:\NS-Final Studio\ops\autostart\laptop_autostart.ps1`""

$bash = '"C:\Program Files\Git\bin\bash.exe"'
schtasks /Create /TN "NSFS-sync_laptop"   /SC MINUTE /MO 10 /F /TR "$bash `"D:/NS-Final Studio/ops/sync/sync_laptop.sh`""
schtasks /Create /TN "NSFS-mirror_prune"  /SC MINUTE /MO 10 /F /TR "$bash `"D:/NS-Final Studio/ops/sync/mirror_prune.sh`""
schtasks /Create /TN "NSFS-pull_laptop"   /SC MINUTE /MO 15 /F /TR "$bash `"D:/NS-Final Studio/ops/sync/pull_laptop.sh`""
schtasks /Create /TN "NSFS-previews_sync" /SC MINUTE /MO 15 /F /TR "$bash `"D:/NS-Final Studio/ops/sync/previews_sync.sh`""
schtasks /Create /TN "NSFS-music_sync"    /SC MINUTE /MO 15 /F /TR "$bash `"D:/NS-Final Studio/ops/sync/music_sync.sh`""

schtasks /Run /TN "NS-Studio-Laptop-Autostart"
schtasks /Query /FO TABLE | Select-String "NS-Studio|NSFS-"
