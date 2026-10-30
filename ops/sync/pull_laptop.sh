#!/bin/bash
# laptop -> gpu3: shared import (adult flags) + the laptop's ACTIVE first/last frames (data/renders/epXX/SN/frame.png, last.png)
# Single run; Windows Scheduled Task "NSFS-pull_laptop", every 10 min.  Log: ops\logs\pull_laptop.log
# 封板修复：script_v2.json 先传 <目标>.tmp 再 ssh mv -f 原子替换（原先直接覆盖，桥读到半截 JSON 当 {} → adult_shots 为空），
#           失败记 rc=1 不再报 "pull ok"；同样方式推 import/s1_gate.json（渲染器 S1 闸门）、state_timeline.json（桥 s2_ready）、
#           scenes.json，原先没推，gpu3 上一直是旧的。
source "$(dirname "$0")/_common.sh"
L="/d/NS-Final Studio/data"
R=/root/claude-kimi-ns-studio-v1/nsfs_mirror/data
rc=0
# push <path relative to data/>: upload to <target>.tmp, then atomic mv on gpu3
push() {
  if [ ! -f "$L/$1" ]; then date "+%F %T push $1: not on laptop, skipped"; return; fi
  if scp -q $SSH_OPTS "$L/$1" "gpu33:$R/$1.tmp" && ssh -n $SSH_OPTS gpu33 "mv -f $R/$1.tmp $R/$1"; then
    :
  else
    date "+%F %T push $1 FAILED"; rc=1
  fi
}
push import/script_v2.json
push import/s1_gate.json
push state_timeline.json
push scenes.json
T=$(mktemp -d)
( cd "$L/renders" && find . -maxdepth 3 \( -name frame.png -o -name last.png -o -name takes.json \) -print0 | tar cf "$T/f.tar" --null -T - ) && \
  scp -q $SSH_OPTS "$T/f.tar" gpu33:/tmp/laptop_frames.tar && \
  ssh -n $SSH_OPTS gpu33 "mkdir -p $R/renders_laptop && tar xf /tmp/laptop_frames.tar -C $R/renders_laptop && date -u +%FT%TZ > $R/renders_laptop/.pulled_at" || rc=1
rm -rf "$T"
if [ $rc = 0 ]; then date "+%F %T pull ok"; else date "+%F %T pull FAILED"; fi
exit $rc
