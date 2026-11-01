#!/bin/sh
# Narrator TTS launcher on gpu36 (VOICE 2026-10-31). Usage: run_narrator.sh <request.json> <gpu idx list> <max_used_mb>
# Picks the first listed GPU whose used memory < max_used_mb and whose per-card lock is free (queue <= 1 per card,
# shared with PLANB / render lanes); otherwise runs on CPU. Never touches other users' processes.
REQ="$1"; GPUS="${2:-2 0 1}"; MAXU="${3:-13500}"
BASE=/root/work/fredw
PY=$BASE/venv_tts/bin/python
HERE=$(dirname "$0")
export HF_HOME=$BASE/hf HF_HUB_OFFLINE=1 OMP_NUM_THREADS=16
ENGINE=$($PY -c "import json,sys;print(json.load(open(sys.argv[1]))['engine'])" "$REQ") || exit 2
if [ "$ENGINE" = "cosyvoice3_zs" ]; then export PYTHONPATH=$BASE/venv_tts/cosy_overlay; fi
mkdir -p $BASE/narrator_tts/locks
for g in $GPUS; do
  USED=$(nvidia-smi -i "$g" --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null) || continue
  [ "$USED" -lt "$MAXU" ] || continue
  exec 9>$BASE/narrator_tts/locks/gpu$g.lock
  if flock -n 9; then
    UUID=$(nvidia-smi -i "$g" --query-gpu=uuid --format=csv,noheader)
    $PY -c "import json,sys;r=json.load(open(sys.argv[1]));r['device']='cuda:0';json.dump(r,open(sys.argv[1],'w'),ensure_ascii=False)" "$REQ"
    echo "narrator_tts: gpu$g used=${USED}MiB" >&2
    CUDA_VISIBLE_DEVICES=$UUID exec $PY "$HERE/narrator_batch.py" "$REQ"
  fi
  exec 9>&-
done
echo "narrator_tts: no idle GPU, using CPU" >&2
$PY -c "import json,sys;r=json.load(open(sys.argv[1]));r['device']='cpu';json.dump(r,open(sys.argv[1],'w'),ensure_ascii=False)" "$REQ"
CUDA_VISIBLE_DEVICES="" exec $PY "$HERE/narrator_batch.py" "$REQ"
