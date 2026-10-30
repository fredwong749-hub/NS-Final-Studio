#!/bin/bash
# 笔记本 → gpu3 常驻 ssh 隧道（断线 30 s 重连）：15180 → 画布渲染桥 :5180；18098 → Qwen 写作模型 :8098；
# 18099 → Qwen 信箱 :8099。由 ops/autostart/laptop_autostart.ps1 在登录时拉起；已在跑就不重复（ops/logs/tunnel.lock）。
# 18188 → gpu3 GPU0 ComfyUI（Image 2.1 出图）；18191 → gpu3 GPU3 ComfyUI（MiniMax H3 视频）——项目方 2026-10-30 夜：画布改了就重出，直接走 gpu3。
# 封板修复：去掉本文件自己的 trap 'rm -rf "$LOCK"'，改用 _common.sh 的 _release_lock（只删仍写着本进程 pid 的锁）
source "$(dirname "$0")/../sync/_common.sh"
while true; do
  ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
      -L 15180:127.0.0.1:5180 -L 18098:127.0.0.1:8098 -L 18099:127.0.0.1:8099 -L 18188:127.0.0.1:8188 -L 18191:127.0.0.1:8191 gpu33
  date "+%F %T tunnel exited ($?), reconnect in 30 s"
  sleep 30
done
