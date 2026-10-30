#!/bin/bash
# Laptop-side sync for the weita series (single run; Windows Scheduled Task "NSFS-sync_laptop", every 10 min):
#  gpu3 renders_gpu3 (takes, finals, sheets, rerender_events.jsonl) -> D:\NS-Final Studio\data\renders_gpu3\  (incremental)
#  finals + contact sheets -> D:\NS-Final Studio\previews\weita_epXX\
#  laptop rerender_queue.jsonl (old ns_api appends) -> merged INTO the gpu3 queue by request id (gpu3 is the source of truth),
#  then the gpu3 queue is downloaded over the laptop copy (ns_api mirror fallback reads it; ns_api no longer appends locally)
# 封板修复 S2/S3/S5：合并补换行、非对象行跳过、合并失败不报 ok 也不覆盖本机队列；合并成功后才下载 gpu3 队列
# Never writes into D:\NS-Final Studio\data\renders\.  Log: ops\logs\sync_laptop.log
# 封板修复：增量下载（ssh|tar）失败记 rc、报 FAILED 并 exit 1（原先照样报 "sync ok"）；pipefail；ssh/scp 加保活（SSH_OPTS）
source "$(dirname "$0")/_common.sh"
set -o pipefail
rc=0
R=/root/claude-kimi-ns-studio-v1/nsfs_mirror/data/renders_gpu3
L="/d/NS-Final Studio/data/renders_gpu3"
P="/d/NS-Final Studio/previews"
STAMP="$L/.last_sync_gpu3"
SSH="ssh -n $SSH_OPTS"
mkdir -p "$L"
since=$(cat "$STAMP" 2>/dev/null || echo 0)
start=$($SSH gpu33 'date +%s') || { date "+%F %T gpu3 unreachable"; exit 1; }
# merge the laptop queue into the gpu3 queue by id (before the gpu3 queue is downloaded over it)
if [ -s "$L/rerender_queue.jsonl" ]; then
  scp -q $SSH_OPTS "$L/rerender_queue.jsonl" gpu33:/tmp/weita_laptop_queue.jsonl && \
  $SSH gpu33 "python3 - <<'EOF'
import json, pathlib
g = pathlib.Path('$R/rerender_queue.jsonl'); l = pathlib.Path('/tmp/weita_laptop_queue.jsonl')
def rows(p):
    for ln in p.read_text(encoding='utf-8').splitlines():
        try: r = json.loads(ln)
        except ValueError: continue
        if isinstance(r, dict): yield ln, r
have = {r.get('id') for _, r in rows(g)} if g.exists() else set()
new = []
for ln, r in rows(l):
    if r.get('id') and r['id'] not in have:
        new.append(ln); have.add(r['id'])
if new:
    lead = '\n' if g.exists() and g.stat().st_size and not g.read_bytes().endswith(b'\n') else ''
    with g.open('a', encoding='utf-8') as f: f.write(lead + '\n'.join(new) + '\n')
print('merged', len(new))
EOF" || { date "+%F %T queue merge FAILED (laptop queue kept, nothing downloaded)"; exit 1; }
fi
if $SSH gpu33 "cd $R 2>/dev/null && find . -type f -newermt @$since ! -name rerender_queue.jsonl ! -name '*.tmp' -print0 | tar cf - --null -T -" | tar xf - -C "$L"; then
  echo "$start" > "$STAMP"
else
  rc=1; date "+%F %T renders download FAILED (stamp not advanced)"
fi
if $SSH gpu33 "cat $R/rerender_queue.jsonl 2>/dev/null || true" > "$L/.rerender_queue.tmp"; then
  mv -f "$L/.rerender_queue.tmp" "$L/rerender_queue.jsonl"
else
  rm -f "$L/.rerender_queue.tmp"; rc=1; date "+%F %T queue download failed (laptop copy kept)"
fi
for d in "$L"/ep*/; do
  [ -d "$d" ] || continue
  ep=$(basename "$d")
  for f in "$d/${ep}_final.mp4" "$d/${ep}_contact.jpg"; do
    [ -f "$f" ] || continue
    mkdir -p "$P/weita_$ep"
    if [ ! -f "$P/weita_$ep/$(basename "$f")" ] || [ "$f" -nt "$P/weita_$ep/$(basename "$f")" ]; then cp "$f" "$P/weita_$ep/"; fi
  done
done
if [ $rc = 0 ]; then date "+%F %T sync ok"; else date "+%F %T sync FAILED"; fi
exit $rc
