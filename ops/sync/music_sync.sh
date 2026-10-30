#!/bin/bash
# gpu3 nsfs_mirror/data/music -> D:\NS-Final Studio\data\music (BGM from audio_post.py)
# Single run; Windows Scheduled Task "NSFS-music_sync", every 15 min.  Log: ops\logs\music_sync.log
# 封板修复：pipefail（ssh 失败时 tar 读空输入也会返回 0，原先照样报 "music ok"）；ssh 加保活（SSH_OPTS）
source "$(dirname "$0")/_common.sh"
set -o pipefail
R=/root/claude-kimi-ns-studio-v1/nsfs_mirror/data/music
L="/d/NS-Final Studio/data/music"
mkdir -p "$L"
if ssh -n $SSH_OPTS gpu33 "cd $R 2>/dev/null && tar cf - ." | tar xf - -C "$L"; then
  date "+%F %T music ok"
else
  date "+%F %T music FAILED"; exit 1
fi
