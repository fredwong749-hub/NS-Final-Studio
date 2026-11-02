#!/bin/bash
# 服务器多剧常驻：给 config/pipeline/runs.json 里 status=producing、且不是 primary 的每部剧各保一个 producer serve --run <run>
# （WORKFLOW 11-02，总调度派：第二季 series10_s2 和第一季同一套管理；规则 K-OPS-W25）。
# 只起不在的；$OFF/STOP 存在时不起（和 start.sh 同语义）。pid / 日志：data/producer/runs/<run>/serve.pid、producer.out（producer.pid 是 producer 自己的锁文件，JSON，不能占）。
# 调用方：resident_restart.sh（重启时连同第二季一起起）、resident_sync.health 每拍（挂了自动拉起）。
# 用法：bash ensure_runs.sh gpu33|gpu36 [stop]
set -u
SELF=$1; ACT=${2:-ensure}; OFF=/root/work/fredw/offline_20261101
R=$OFF/repo
cd $R || exit 1
RUNS=$($OFF/venv/bin/python - <<'PY'
import json
try:
    d = json.load(open("config/pipeline/runs.json", encoding="utf-8"))
except Exception:
    d = {}
prim = d.get("primary")
print(" ".join(k for k, v in (d.get("runs") or {}).items() if k != prim and (v or {}).get("status") == "producing"))
PY
)
alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null && grep -q "producer.py" /proc/$(cat "$1")/cmdline 2>/dev/null; }
if [ "$ACT" = "stop" ]; then
  for f in data/producer/runs/*/serve.pid; do
    [ -f "$f" ] || continue
    if alive $f; then p=$(cat $f); kill $p; for i in $(seq 1 15); do kill -0 $p 2>/dev/null || break; sleep 1; done
      kill -0 $p 2>/dev/null && kill -9 $p; echo "stopped producer[$(basename $(dirname $f))] $p"; fi
  done
  exit 0
fi
[ -f $OFF/STOP ] && { echo "STOP 存在：不起额外剧 producer"; exit 0; }
export TZ=Asia/Tokyo OFFLINE_SELF=$SELF OFFLINE_ALIASES=$([ $SELF = gpu36 ] && echo gpu33) PATH=$OFF/bin:$PATH PYTHONUTF8=1 PYTHONIOENCODING=utf-8
export NS_QC_VISION_DIR=/root/work/fredw/video10_srv/models_cache/vision
for run in $RUNS; do
  d=data/producer/runs/$run; mkdir -p $d
  if alive $d/serve.pid; then echo "producer[$run] pid $(cat $d/serve.pid) alive"; continue; fi
  setsid nohup $OFF/venv/bin/python -u tools/autopilot/producer.py serve --run $run </dev/null >>$d/producer.out 2>&1 &
  echo $! >$d/serve.pid
  sleep 2
  echo "producer[$run] pid $(cat $d/serve.pid) $(alive $d/serve.pid && echo started || echo DEAD)"
done
