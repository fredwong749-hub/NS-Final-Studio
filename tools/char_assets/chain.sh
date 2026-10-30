#!/bin/bash
# Auto-chain on gpu3 so GPU time is used whenever GPU 1 / a lent GPU frees up:
#   stage1 + nails (already running)  ->  stage2 (from the provisional front plate)  ->  stage3 (worn items, nails in context, looks)
# Provisional picks (overridable by dropping a file into refs/ before the stage starts):
#   LW-ID-F    = out/stage1/proto_idF_base.png       BODY-F = out/stage2/lw_plate_BODY-F.png
#   products   = out/stage1/lw_item_*_prod.png        nails  = out/nails/lw_nail_N1_BK_1.png, lw_toe_T1_HEEL.png
# Everything produced here is a CANDIDATE; nothing is delivered to the laptop until reviewed (collect.py deliver).
set -u
A=/root/claude-kimi-ns-studio-v1/nsfs_assets
PY=/root/claude-kimi-ns-studio-v1/env/comfy/bin/python
cd $A
log() { echo "$(date '+%F %T') $*" >> logs/chain.log; }
wait_done() { until grep -q ALL_DONE logs/$1.log 2>/dev/null; do sleep 60; done; }
scale() {  # src dst maxside
  $PY - "$1" "$2" "$3" <<'EOF'
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("RGB"); m = int(sys.argv[3])
im.thumbnail((m, m), Image.LANCZOS); im.save(sys.argv[2])
EOF
}
run() { $PY -u tools/asset_gen.py jobs/$1.jsonl out/$1 >> logs/$1.log 2>&1; }

log "chain start"; wait_done stage1
[ -f refs/LW-ID-F.png ] || scale out/stage1/proto_idF_base.png refs/LW-ID-F.png 768
(cd tools && $PY build_jobs.py stage2 LW-ID-F.png) && mv tools/jobs/stage2.jsonl jobs/
log "stage2 start"; run stage2; log "stage2 done"
for f in out/stage1/lw_item_*_prod.png; do b=$(basename $f); [ -f refs/$b ] || scale $f refs/$b 768; done
[ -f refs/lw_plate_BODY-F.png ] || cp out/stage2/lw_plate_BODY-F.png refs/lw_plate_BODY-F.png
wait_done nails
[ -f refs/lw_nail_N1_BK.png ] || scale out/nails/lw_nail_N1_BK_1.png refs/lw_nail_N1_BK.png 768
[ -f refs/lw_toe_T1_HEEL.png ] || scale out/nails/lw_toe_T1_HEEL.png refs/lw_toe_T1_HEEL.png 768
(cd tools && $PY build_jobs.py stage3 LW-ID-F.png lw_plate_BODY-F.png) && mv tools/jobs/stage3.jsonl jobs/
log "stage3 start"; run stage3; log "stage3 done; chain finished"
