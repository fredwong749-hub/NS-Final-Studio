#!/bin/bash
# gpu3 nsfs_mirror/data/music -> D:\NS-Final Studio\data\music (BGM from audio_post.py), every 15 min
R=/root/claude-kimi-ns-studio-v1/nsfs_mirror/data/music
L="/d/NS-Final Studio/data/music"
mkdir -p "$L"
while true; do
  ssh -n -o BatchMode=yes -o ConnectTimeout=30 gpu33 "cd $R 2>/dev/null && tar cf - ." | tar xf - -C "$L" && date "+%F %T music ok"
  sleep 900
done
