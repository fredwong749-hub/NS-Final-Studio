#!/bin/bash
# Laptop-side sync for the weita series (runs while this Claude session lives):
#  gpu3 renders_gpu3 (takes, finals, sheets, rerender_events.jsonl) -> D:\NS-Final Studio\data\renders_gpu3\  (incremental)
#  finals + contact sheets -> D:\NS-Final Studio\previews\weita_epXX\
#  laptop rerender_queue.jsonl (ns_api) -> merged INTO the gpu3 queue by request id (gpu3 is the source of truth)
# Never writes into D:\NS-Final Studio\data\renders\.
R=/root/claude-kimi-ns-studio-v1/nsfs_mirror/data/renders_gpu3
L="/d/NS-Final Studio/data/renders_gpu3"
P="/d/NS-Final Studio/previews"
STAMP="$L/.last_sync_gpu3"
SSH="ssh -n -o BatchMode=yes -o ConnectTimeout=30"
mkdir -p "$L"
while true; do
  since=$(cat "$STAMP" 2>/dev/null || echo 0)
  start=$($SSH gpu33 'date +%s') || { sleep 60; continue; }
  if $SSH gpu33 "cd $R 2>/dev/null && find . -type f -newermt @$since ! -name rerender_queue.jsonl ! -name '*.tmp' -print0 | tar cf - --null -T -" | tar xf - -C "$L"; then
    echo "$start" > "$STAMP"
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
  # merge the laptop queue (ns_api) into the gpu3 queue by id
  if [ -s "$L/rerender_queue.jsonl" ]; then
    scp -q -o BatchMode=yes -o ConnectTimeout=30 "$L/rerender_queue.jsonl" gpu33:/tmp/weita_laptop_queue.jsonl && \
    $SSH gpu33 "python3 - <<'EOF'
import json, pathlib
g = pathlib.Path('$R/rerender_queue.jsonl'); l = pathlib.Path('/tmp/weita_laptop_queue.jsonl')
def ids(p):
    out = set()
    if p.exists():
        for ln in p.read_text(encoding='utf-8').splitlines():
            try: out.add(json.loads(ln).get('id'))
            except ValueError: pass
    return out
have = ids(g); new = []
for ln in l.read_text(encoding='utf-8').splitlines():
    try: r = json.loads(ln)
    except ValueError: continue
    if r.get('id') and r['id'] not in have:
        new.append(ln); have.add(r['id'])
if new:
    with g.open('a', encoding='utf-8') as f: f.write('\n'.join(new) + '\n')
print('merged', len(new))
EOF"
  fi
  date "+%F %T sync ok"
  sleep 600
done
