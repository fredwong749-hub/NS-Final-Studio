#!/bin/bash
# copy passing frames (gpu3 renders_gpu3/epXX/frames_preview) to D:\NS-Final Studio\previews\frames\epXX\ for the owner
R=/root/claude-kimi-ns-studio-v1/nsfs_mirror/data/renders_gpu3
P="/d/NS-Final Studio/previews/frames"
while true; do
  T=$(mktemp -d)
  if ssh -n -o BatchMode=yes -o ConnectTimeout=30 gpu33 "cd $R && ls -d ep*/frames_preview >/dev/null 2>&1 && tar cf - ep*/frames_preview" > "$T/p.tar" 2>/dev/null && [ -s "$T/p.tar" ]; then
    mkdir -p "$T/x" && tar xf "$T/p.tar" -C "$T/x"
    for d in "$T"/x/ep*/frames_preview; do ep=$(basename "$(dirname "$d")"); mkdir -p "$P/$ep"; cp -u "$d"/* "$P/$ep/" 2>/dev/null; done
    date "+%F %T previews ok"
  fi
  rm -rf "$T"
  sleep 900
done
