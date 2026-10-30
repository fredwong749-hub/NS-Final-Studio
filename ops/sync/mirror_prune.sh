#!/bin/bash
# Mirror deletions gpu3 -> laptop for renders_gpu3 shot files (frame/last/video/takes.json/last_target; status.json is NOT pruned).
# Files gone on gpu3 are MOVED to data/renders_gpu3/_pruned/<date>/ (not deleted).
# 封板修复 S1：两边 sort 与 comm 都用 LC_ALL=C（gpu3 en_US 与 Git Bash C 排序不同，comm 会把活文件误移到 _pruned）
# 封板修复：先列本机、再列 gpu3（原先反过来，两次列表之间被 sync_laptop 新下载的文件会被当成"gpu3 已删"移走）；
#           远端命令加 set -o pipefail，find 失败不会交出半截列表。
# Single run; Windows Scheduled Task "NSFS-mirror_prune", every 10 min.  Log: ops\logs\mirror_prune.log
source "$(dirname "$0")/_common.sh"
R=/root/claude-kimi-ns-studio-v1/nsfs_mirror/data/renders_gpu3
L="/d/NS-Final Studio/data/renders_gpu3"
remote=$(mktemp); localf=$(mktemp)
if (set -o pipefail; cd "$L" && find . -path './_pruned' -prune -o -path './ep*/S*' -type f \( -name frame.png -o -name last.png -o -name video.mp4 -o -name takes.json -o -name last_target.png \) -print | LC_ALL=C sort) > "$localf" && \
   ssh -n $SSH_OPTS gpu33 "set -o pipefail; cd $R && find . -path './ep*/S*' -type f \( -name frame.png -o -name last.png -o -name video.mp4 -o -name takes.json -o -name last_target.png \) | LC_ALL=C sort" > "$remote" 2>/dev/null && [ -s "$remote" ]; then
  n=0
  while IFS= read -r f; do
    d="$L/_pruned/$(date +%F)/$(dirname "$f")"; mkdir -p "$d" && mv "$L/$f" "$d/" && n=$((n+1))
  done < <(LC_ALL=C comm -23 "$localf" "$remote")
  date "+%F %T prune ok moved=$n"
else
  date "+%F %T prune skipped (local list failed, gpu3 unreachable or empty remote list; nothing moved)"
fi
rm -f "$remote" "$localf"
