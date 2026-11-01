#!/bin/bash
# lb_runner.sh — fredw-92/LB overnight image-LoRA queue on gpu33 (owner 2026-10-31: "lora 和 blender 那个任务我已经授权了，gpu 空闲就跑起来").
# Scope (coordinator fredw-92): jewellery nprng2 / lbrng9 / lbrng9_beads. lnwan01 / pose LoRAs belong to fredw-0b (T64).
# Lane: GPU3 only (GPU0 = ND tonight, GPU1 = fredw-0b, GPU2 never). A training run starts only after GPU3 has been idle
# for IDLE_MIN minutes (ComfyUI :8191 queue empty, util < 10 %, no gpu.lock/lend/foreign train.lock). Production wins:
# if anything lands in :8191's queue or a lend/gpu.lock appears while we train, we stop OUR trainer (process group we
# started), release the locks and wait again; ai-toolkit resumes from its last checkpoint (save_every 250).
# Steps per concept are idempotent (state markers in $LB/state). Restart = run this script again.
# Captions for new datasets come only from the writer LLM (lora_llm), copied verbatim to $LB/captions_llm/<concept>/.
# Registry status is "candidate" (accepting is the owner's / QA's call). No content judgement anywhere in here.
set -u
R=/root/claude-kimi-ns-studio-v1
J=$R/ns-studio/data/train/jewellery
T=$J/tools
LB=$R/ns-studio/data/train/lb
ST=/root/.local/state/NS-Studio
PY=$R/env/comfy/bin/python
AITK=$R/env/trainers/ai-toolkit
G=${LB_GPU:-3}; PORT=8191
IDLE_MIN=${IDLE_MIN:-30}
JOBS=${JOBS:-"nprng2 lbrng9 lbrng9_beads"}
[ "$G" = 3 ] || { echo "lb_runner: only GPU3 is assigned to fredw-92/LB on gpu33"; exit 2; }
mkdir -p $LB/state $LB/out $LB/logs $ST/lb
log() { echo "$(date '+%F %T') $*" >> $LB/runner.log; }
setstate() { echo "{\"concept\": \"$1\", \"step\": \"$2\", \"at\": \"$(date -Is)\", \"detail\": \"${3:-}\"}" > $LB/state/$1.json; }

qlen() { curl -s -m 10 127.0.0.1:$PORT/queue | python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d["queue_running"])+len(d["queue_pending"]))' 2>/dev/null || echo 99; }
util() { nvidia-smi -i $G --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | tr -d ' ' || echo 100; }
foreign_lock() {  # anything that says someone else owns GPU3 right now
  for f in $ST/lend.gpu$G $ST/lend.gpu$G.pending $ST/gpu.lock.gpu$G; do
    [ -e "$f" ] || continue
    grep -q "lb-train" "$f" 2>/dev/null && continue
    P=$(sed -n 's/^pid:\([0-9]*\).*/\1/p' "$f" 2>/dev/null)
    if [ -n "$P" ] && ! kill -0 "$P" 2>/dev/null; then continue; fi   # dead pid = stale gpu.lock (router rule)
    echo "$f"; return 0
  done
  if [ -e $ST/train.lock.gpu$G ] && ! grep -q '"owner": "fredw-92/LB"' $ST/train.lock.gpu$G; then echo $ST/train.lock.gpu$G; return 0; fi
  return 1
}

wait_idle() {  # block until GPU3 has been idle for IDLE_MIN minutes
  local since="" n=0 why
  while true; do
    why=""
    q=$(qlen); u=$(util)
    [ "$q" != 0 ] && why="comfy queue $q"
    [ "${u:-100}" -ge 10 ] && why="$why util $u%"
    fl=$(foreign_lock) && why="$why lock $fl"
    if [ -z "$why" ]; then
      [ -z "$since" ] && since=$(date +%s)
      [ $(( $(date +%s) - since )) -ge $(( IDLE_MIN * 60 )) ] && return 0
    else
      since=""
    fi
    [ $((n % 15)) = 0 ] && log "waiting for GPU$G idle ${IDLE_MIN}min (${why:-idle since $(date -d @$since +%T)})"
    n=$((n + 1)); sleep 60
  done
}

take_locks() {  # $1 job
  ( set -C; echo "{\"by\": \"lb_runner\", \"gpu\": $G, \"owner\": \"fredw-92/LB\", \"job\": \"$1\", \"since\": \"$(date -Is)\", \"pid\": $$}" > $ST/train.lock.gpu$G ) 2>/dev/null || return 1
  if ! ( set -C; echo -n "pid:$$ lb-train:$1" > $ST/gpu.lock.gpu$G ) 2>/dev/null; then rm -f $ST/train.lock.gpu$G; return 1; fi
  return 0
}
release_locks() {
  grep -q '"owner": "fredw-92/LB"' $ST/train.lock.gpu$G 2>/dev/null && rm -f $ST/train.lock.gpu$G
  grep -q "lb-train" $ST/gpu.lock.gpu$G 2>/dev/null && rm -f $ST/gpu.lock.gpu$G
}
TPID=""
on_exit() { [ -n "$TPID" ] && kill -TERM -"$TPID" 2>/dev/null; sleep 5; release_locks; log "runner exit"; }
trap on_exit EXIT
trap 'exit 130' INT TERM

photoreal() {  # $1 concept (per-image ComfyUI jobs on :8191 only, each after 10 min of quiet)
  local c=$1
  [ -e $LB/state/$c.photoreal_done ] && return 0
  setstate $c photoreal
  log "photoreal $c (GPU3 only, quiet 600 s per image)"
  $PY -u $T/jwl_photoreal.py --render $J/render --concept $c --tag v1 --gpu $G --allowed $G --quiet 600 >> $LB/logs/photoreal_$c.log 2>&1
  local rc=$?
  log "photoreal $c exit $rc"
  [ $rc = 0 ] && touch $LB/state/$c.photoreal_done
  return $rc
}

dataset() {  # $1 concept: LLM captions only (lbrng9, lbrng9_beads); nprng2 keeps its existing dataset files
  local c=$1
  [ -e $LB/state/$c.dataset_done ] && return 0
  if [ "$c" = nprng2 ]; then touch $LB/state/$c.dataset_done; return 0; fi
  local cap=$LB/captions_llm/$c
  [ -n "$(ls $cap/*.txt 2>/dev/null)" ] || { log "no LLM captions in $cap yet"; return 1; }
  setstate $c dataset
  $PY -I $T/jwl_dataset.py --render $J/render --concept $c --tag v1 --out $J/$c --max 60 --captions $cap >> $LB/logs/dataset_$c.log 2>&1 || return 1
  local n=$(ls $J/$c/*.png 2>/dev/null | wc -l)
  log "dataset $c: $n images (captions: lora_llm, verbatim)"
  [ "$n" -ge 10 ] || { log "dataset $c too small ($n < 10)"; return 1; }
  (cd $J/$c && COLS=8 $PY -I $T/sheet.py $J/sheets/${c}_dataset_sheet.jpg 360 $(ls *.png | sort)) >> $LB/logs/dataset_$c.log 2>&1
  touch $LB/state/$c.dataset_done
}

train() {  # $1 concept; resumable, preemptible
  local c=$1 name=jewellery_$1_v1
  local out=$J/runs/$name cfg=$J/configs/$name.json
  [ -f $out/$name.safetensors ] && return 0
  [ -f $cfg ] || { log "missing config $cfg"; return 1; }
  while true; do
    setstate $c wait_gpu
    wait_idle
    take_locks $name || { log "lock race on GPU$G, waiting again"; sleep 60; continue; }
    curl -s -m 30 -X POST 127.0.0.1:$PORT/free -H 'Content-Type: application/json' -d '{"unload_models": true, "free_memory": true}' >/dev/null
    sleep 15
    setstate $c train "GPU$G"
    log "train $name on GPU$G (last ckpt: $(ls $out/${name}_0*.safetensors 2>/dev/null | tail -1 | xargs -r basename))"
    (cd $AITK && CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=$G HF_HUB_OFFLINE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
       exec setsid $R/env/aitk/bin/python run.py $cfg) >> $J/logs/train_$name.log 2>&1 &
    TPID=$!
    echo $TPID > $LB/state/train.pid
    local pre=""
    while kill -0 $TPID 2>/dev/null; do
      sleep 30
      q=$(qlen); fl=$(foreign_lock)
      if [ "$q" != 0 ] && [ "$q" != 99 ] || [ -n "$fl" ]; then pre="queue=$q lock=$fl"; break; fi
    done
    if [ -n "$pre" ]; then
      log "PREEMPT $name ($pre): stopping our trainer pgid $TPID"
      kill -TERM -$TPID 2>/dev/null; for i in $(seq 1 30); do kill -0 $TPID 2>/dev/null || break; sleep 2; done
      kill -KILL -$TPID 2>/dev/null
    fi
    wait $TPID 2>/dev/null; local rc=$?
    TPID=""; rm -f $LB/state/train.pid
    release_locks
    if [ -f $out/$name.safetensors ]; then log "train $name finished"; return 0; fi
    log "train $name stopped rc=$rc ${pre:+(preempted)}; will resume from last checkpoint"
    if [ -z "$pre" ]; then
      FAILS=$(( ${FAILS:-0} + 1 ))
      [ $FAILS -ge 3 ] && { log "train $name failed 3 times, giving up (see $J/logs/train_$name.log)"; setstate $c failed "see train log"; return 1; }
      sleep 300
    fi
  done
}

post() {  # $1 concept: deploy file + sha256 + registry "candidate" + technical metrics + sample sheet
  local c=$1 name=jewellery_$1_v1
  local out=$J/runs/$name
  [ -e $LB/state/$c.post_done ] && return 0
  cp $out/$name.safetensors $R/ComfyUI/models/loras/$name.safetensors.tmp && mv $R/ComfyUI/models/loras/$name.safetensors.tmp $R/ComfyUI/models/loras/$name.safetensors
  local sha=$(sha256sum $R/ComfyUI/models/loras/$name.safetensors | cut -d' ' -f1)
  echo "$sha  $name.safetensors" >> $J/LORA_SHA256.txt
  $PY -I $T/lora_registry.py --id $name --file $name.safetensors --trigger $c --status candidate --strength 0.8 --sha256 $sha \
     --note "fredw-92/LB $(date -Is): trained on gpu33 GPU$G (ai-toolkit, configs/$name.json). candidate = not reviewed; accept/reject is owner/QA. captions: $([ $c = nprng2 ] && echo 'existing dataset files' || echo 'lora_llm (abliteration large-flash) verbatim')" >> $LB/logs/post_$c.log 2>&1
  (cd $out/samples 2>/dev/null && COLS=6 $PY -I $T/sheet.py $J/sheets/${name}_samples.jpg 400 $(ls *.jpg *.png 2>/dev/null | sort)) >> $LB/logs/post_$c.log 2>&1 || true
  python3 - "$J/logs/train_$name.log" "$out" "$name" "$sha" > $LB/out/$name.json <<'EOF'
import json, os, re, sys
log, out, name, sha = sys.argv[1:]
txt = open(log, errors="replace").read() if os.path.exists(log) else ""
steps = re.findall(r"\|\s*(\d+)/(\d+) \[[^\]]*\][^\n\r]*?loss: ([0-9.e+-]+)", txt)
ck = sorted(f for f in os.listdir(out) if f.endswith(".safetensors"))
print(json.dumps({"lora": name, "sha256": sha, "status": "candidate", "checkpoints": ck,
                  "last_logged": {"step": int(steps[-1][0]), "of": int(steps[-1][1]), "loss": float(steps[-1][2])} if steps else None,
                  "losses_tail": [float(s[2]) for s in steps[-20:]],
                  "file_bytes": os.path.getsize(os.path.join(out, name + ".safetensors")),
                  "samples_dir": os.path.join(out, "samples")}, indent=1))
EOF
  setstate $c candidate "sha256 $sha"
  log "post $name: candidate sha256 $sha"
  touch $LB/state/$c.post_done
}

echo $$ > $LB/runner.pid
log "runner start pid $$ jobs: $JOBS"
for c in $JOBS; do
  if ! ( set -C; echo "gpu33:GPU$G pid:$$ $(date -Is)" > $ST/lb/claim.$c ) 2>/dev/null; then
    grep -q "gpu33" $ST/lb/claim.$c || { log "skip $c: claimed by $(cat $ST/lb/claim.$c)"; continue; }
  fi
  [ -e $LB/state/$c.post_done ] && { log "$c already done"; continue; }
  if [ "$c" != nprng2 ]; then photoreal $c || { log "photoreal $c incomplete, continuing with what exists"; }; fi
  dataset $c || { setstate $c blocked "dataset not ready"; continue; }
  train $c || continue
  post $c
done
log "runner finished"
