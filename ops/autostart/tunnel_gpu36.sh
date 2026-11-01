#!/bin/bash
# fredw-92/G36：笔记本 → gpu36 常驻 ssh 隧道（断线 30 s 重连），gpu36 的三个 ComfyUI 渲染道：
#   18288 → gpu36 :8188（GPU0，道 gpu36:0）  18289 → :8189（GPU1，gpu36:1）  18290 → :8190（GPU2，gpu36:2）
# 由 tunnel.sh（gpu33 隧道）顺带拉起，也由 laptop_autostart.ps1 在三个端口任一不在监听时拉起；自带锁（ops/logs/tunnel_gpu36.lock），重复启动自己退出。
# gpu36 上的实例：/root/work/fredw/comfy/comfy.sh start|stop|status（见 docs/USER_GUIDE_v1.md 本地实现 gpu36 一节）。
source "$(dirname "$0")/../sync/_common.sh"
while true; do
  ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -o IPQoS=throughput \
      -L 18288:127.0.0.1:8188 -L 18289:127.0.0.1:8189 -L 18290:127.0.0.1:8190 gpu36
  date "+%F %T tunnel_gpu36 exited ($?), reconnect in 30 s"
  sleep 30
done
