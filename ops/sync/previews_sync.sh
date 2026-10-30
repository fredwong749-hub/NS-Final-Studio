#!/bin/bash
# copy passing frames (gpu3 renders_gpu3/epXX/frames_preview) to D:\NS-Final Studio\previews\frames\epXX\ for the owner
# Single run; Windows Scheduled Task "NSFS-previews_sync", every 10 min.  Log: ops\logs\previews_sync.log
# 封板修复：解包 / 复制失败记 rc，报 FAILED 并 exit 1（原先一律报 "previews ok"）
source "$(dirname "$0")/_common.sh"
R=/root/claude-kimi-ns-studio-v1/nsfs_mirror/data/renders_gpu3
P="/d/NS-Final Studio/previews/frames"
T=$(mktemp -d)
rc=0
if ssh -n $SSH_OPTS gpu33 "cd $R && ls -d ep*/frames_preview >/dev/null 2>&1 && tar cf - ep*/frames_preview" > "$T/p.tar" 2>/dev/null && [ -s "$T/p.tar" ]; then
  if mkdir -p "$T/x" && tar xf "$T/p.tar" -C "$T/x"; then
    for d in "$T"/x/ep*/frames_preview; do
      [ -d "$d" ] || continue
      ep=$(basename "$(dirname "$d")")
      [ -n "$(ls -A "$d")" ] || continue
      mkdir -p "$P/$ep" && cp -u "$d"/* "$P/$ep/" || rc=1
    done
  else
    rc=1
  fi
  if [ $rc = 0 ]; then date "+%F %T previews ok"; else date "+%F %T previews FAILED"; fi
else
  date "+%F %T previews: nothing fetched (gpu3 unreachable or no frames_preview)"
fi
rm -rf "$T"
exit $rc
