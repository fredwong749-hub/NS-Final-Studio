#!/bin/bash
# laptop -> gpu3: shared import (adult flags) + the laptop's ACTIVE first/last frames (data/renders/epXX/SN/frame.png, last.png)
L="/d/NS-Final Studio/data"
R=/root/claude-kimi-ns-studio-v1/nsfs_mirror/data
while true; do
  scp -q -o BatchMode=yes -o ConnectTimeout=30 "$L/import/script_v2.json" gpu33:$R/import/script_v2.json
  T=$(mktemp -d)
  ( cd "$L/renders" && find . -maxdepth 3 \( -name frame.png -o -name last.png -o -name takes.json \) -print0 | tar cf "$T/f.tar" --null -T - ) && \
    scp -q -o BatchMode=yes -o ConnectTimeout=30 "$T/f.tar" gpu33:/tmp/laptop_frames.tar && \
    ssh -n -o BatchMode=yes -o ConnectTimeout=30 gpu33 "mkdir -p $R/renders_laptop && tar xf /tmp/laptop_frames.tar -C $R/renders_laptop && date -u +%FT%TZ > $R/renders_laptop/.pulled_at"
  rm -rf "$T"
  date "+%F %T pull ok"
  sleep 900
done
