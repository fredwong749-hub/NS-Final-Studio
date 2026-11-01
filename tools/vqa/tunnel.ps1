# VQAGATE 11-01 原为常驻 ssh 循环（127.0.0.1:8871 → gpu36 127.0.0.1:8870）。
# NETFIX 11-01 23:0x（总调度定，K-OPS-N01）：退役，8871 已并入隧道监管进程 tools/netfix/tunnel_supervisor.py 的 gpu36 主连接（config/netfix/tunnels.json）。
# 再运行本脚本只会确保监管进程在跑，不再自己起 ssh（会和监管进程抢端口）。旧版本在 data/_quarantine/netfix_20261101/vqa_tunnel.ps1。
$env:PYTHONUTF8 = "1"
& "D:\NS-Final Studio\.venv\Scripts\python.exe" "D:\NS-Final Studio\tools\netfix\tunnel_supervisor.py" ensure
