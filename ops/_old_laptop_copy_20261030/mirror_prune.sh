#!/bin/bash
# Mirror deletions gpu3 -> laptop for renders_gpu3 shot files (frame/last/video/takes.json/last_target/status.json).
# Files gone on gpu3 are MOVED to data/renders_gpu3/_pruned/<date>/ (not deleted). Every 10 min.
R=/root/claude-kimi-ns-studio-v1/nsfs_mirror/data/renders_gpu3
L="/d/NS-Final Studio/data/renders_gpu3"
while true; do
  remote=$(mktemp); localf=$(mktemp)
  if ssh -n -o BatchMode=yes -o ConnectTimeout=30 gpu33 "cd $R && find . -path './ep*/S*' -type f \( -name frame.png -o -name last.png -o -name video.mp4 -o -name takes.json -o -name last_target.png \) | sort" > "$remote" 2>/dev/null && [ -s "$remote" ]; then
    (cd "$L" && find . -path './_pruned' -prune -o -path './ep*/S*' -type f \( -name frame.png -o -name last.png -o -name video.mp4 -o -name takes.json -o -name last_target.png \) -print | sort) > "$localf"
    n=0
    while IFS= read -r f; do
      d="$L/_pruned/$(date +%F)/$(dirname "$f")"; mkdir -p "$d" && mv "$L/$f" "$d/" && n=$((n+1))
    done < <(comm -23 "$localf" "$remote")
    date "+%F %T prune ok moved=$n"
  fi
  rm -f "$remote" "$localf"
  sleep 600
done
