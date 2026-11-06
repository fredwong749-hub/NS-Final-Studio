#!/bin/bash
# L-206 审图位（项目方 11-06：“一个 gpu 专门出图，另一个 gpu 审图”）：gpu33:3 上 N 个 Qwen3-VL-8B nf4 看图实例 + 分发器 :8870。
# 在 gpu33 上执行；start / stop 由 PS-MASTER 在两集之间手工做；scale N 由阶段钩子（producer lane_roles_tick → lane_roles_producer.review_scale_tick，
# L-207）在阶段切换时调（审图台本机 subprocess / 笔记本 rssh，带超时）。配置单一来源 config/pipeline/lane_roles.json review.{lane, vqa_instances, port_base, vqa_instances_by_phase}：
#   卡 = review.lane 的卡号（gpu33:3 → GPU3）、实例数上限 = vqa_instances（3）、实例端口 = port_base+6+i（8876 8877 8878，避开 8871 隧道 / 8873 8874 打分常驻）、
#   分发器 = port_base（8870，tools/vqa/vqa_router.py，对外接口与单实例一样 → ns_agent.vqa.client 不用改；分发器每次请求按 /health 挑活着的实例，
#   实例少了 / 多了不用重启分发器）。
#   bash tools/vqa/review_instances.sh start [--replace]   # 起全部 N 个实例（已在的不重起）+ 分发器；--replace = 先停 8870 上的旧单实例（start_gpu33_vqa.sh 起的）
#   bash tools/vqa/review_instances.sh scale K             # L-207：只保留前 K 个实例（K ≤ N；frames 3 / videos 1）——多的停（只停本脚本 pid 文件里的），少的起；分发器不在就起；幂等
#   bash tools/vqa/review_instances.sh health              # 健康检查：分发器 + 每个实例 /health + 显存；实例不齐 / 分发器不在 → 退出码 ≠ 0
#   bash tools/vqa/review_instances.sh status              # 同 health，只打印不判退出码
#   bash tools/vqa/review_instances.sh stop                # 只停本脚本 pid 文件里的进程（分发器 + 实例），不碰别的
#   bash tools/vqa/review_instances.sh anomaly             # （可选）本机 CPU 常驻人数 / 身份检测 :8893（accept.review_local_anomaly 探到就用）；需 ANOMALY_PY
# 红线：GPU2 拒绝（坏卡）；显存：N×7.4 GB ≈ 22 GB，该卡 ComfyUI（审图位，首尾帧阶段不收出图单）必须先卸模型，否则两边 OOM；起不动就退出，不 kill 别人的进程。
# 视频阶段（L-207）：该卡只留 1 个实例（7.5 GB），ComfyUI（--reserve-vram 9）同卡出 H3 视频（约 13 GB），scale 1 在进视频段时调；下一集首尾帧段 scale 3 前
# 本脚本会先让 ComfyUI /free 卸模型再起实例。
set -u
CMD=${1:-status}; OPT=${2:-}
REPO=${NS_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
B=${VQA_BASE:-/root/work/fredw/vqa}
CFG=$REPO/config/pipeline/lane_roles.json
[ -f "$CFG" ] || { echo "NO_CFG $CFG"; exit 1; }
eval "$(python3 - "$CFG" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8-sig"))
r = d.get("review") or {}
lane = str(r.get("lane") or "gpu33:3")
host, gpu = lane.split(":", 1)
n = int(r.get("vqa_instances") or 3)
base = int(r.get("port_base") or 8870)
ports = " ".join(str(base + 6 + i) for i in range(n))
print("HOST=%s; GPU=%s; N=%d; ROUTER=%d; PORTS='%s'; ENABLED=%s" % (host, gpu, n, base, ports, "1" if d.get("enabled") else "0"))
PY
)"
[ "$GPU" = 2 ] && { echo "REFUSE ${HOST}:2（坏卡红线）"; exit 2; }
SELF=${OFFLINE_SELF:-$(hostname -s)}
if [ "$SELF" != "$HOST" ] && [ "${FORCE:-0}" != 1 ]; then echo "WRONG_HOST 本机=$SELF 审图位=$HOST（FORCE=1 可越过）"; exit 2; fi
PER_MIB=${VQA_PEAK_MIB:-7500}          # config/vqa.json model.vram_budget：nf4 实例峰值 7206–7386 MiB
COMFY_PORT=$((8188 + GPU))

hjson() { curl -s -m "${2:-4}" "http://127.0.0.1:$1/health"; }
up() { hjson "$1" 2 >/dev/null 2>&1; }

health() {   # $1 = 期望实例数（默认 N）
  want=${1:-$N}
  rc=0; okn=0
  r=$(hjson "$ROUTER"); kind=$(printf '%s' "$r" | python3 -c 'import json,sys
try:
    h=json.load(sys.stdin); print("router" if h.get("gpu")=="router" else "single")
except Exception: print("down")')
  echo "router :$ROUTER = $kind ${r:0:200}"
  [ "$kind" = router ] || rc=1
  for p in $PORTS; do
    h=$(hjson "$p"); if [ -n "$h" ]; then okn=$((okn+1)); echo "instance :$p up ${h:0:160}"; else echo "instance :$p DOWN"; fi
  done
  echo "instances up $okn/$want (max $N)"; [ "$okn" -ge "$want" ] || rc=1
  nvidia-smi -i "$GPU" --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null | sed "s/^/GPU$GPU mem,total,util: /"
  a=$(hjson 8893); [ -n "$a" ] && echo "anomaly :8893 up ${a:0:120}" || echo "anomaly :8893 down（人数检测退回 count_host）"
  return $rc
}

stop_ports() {   # 只停本脚本 pid 文件里的实例（$@ = 端口）
  for p in "$@"; do
    f="$B/server_$p.pid"
    [ -f "$f" ] && { kill "$(cat "$f")" 2>/dev/null && echo "stopped instance :$p ($(basename "$f"))"; rm -f "$f"; }
  done
}

start_instances() {   # $@ = 要保证在跑的实例端口；显存不够先让该卡 ComfyUI 卸模型；仍不够退出 3（不 kill 别人）
  [ -x "$B/venv/bin/python" ] || { echo "NO_VENV $B/venv（先跑 tools/vqa/deploy_offline.sh gpu33）"; return 1; }
  [ -f "$B/models/Qwen3-VL-8B-Instruct/config.json" ] || { echo "NO_MODEL $B/models/Qwen3-VL-8B-Instruct"; return 1; }
  cp "$REPO/tools/vqa/server.py" "$REPO/tools/vqa/vqa_router.py" "$REPO/config/vqa.json" "$B/" || { echo "COPY_FAIL"; return 1; }
  mkdir -p "$B/logs" /root/work/fredw/gpu_heartbeats
  need=0; for p in "$@"; do up "$p" || need=$((need+1)); done
  if [ "$need" -gt 0 ]; then
    FREE=$(nvidia-smi -i "$GPU" --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
    if [ "${FREE:-0}" -lt $((need * PER_MIB)) ]; then      # 该卡 ComfyUI（审图位 / 视频段刚出完视频）卸模型后再量一次；仍不够就退出，不 kill
      curl -s -m 10 -X POST "http://127.0.0.1:$COMFY_PORT/free" -H 'Content-Type: application/json' -d '{"unload_models":true,"free_memory":true}' >/dev/null 2>&1
      sleep 5; FREE=$(nvidia-smi -i "$GPU" --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
    fi
    [ "${FREE:-0}" -ge $((need * PER_MIB)) ] || { echo "VRAM_TOO_LOW GPU$GPU free=${FREE}MiB < $need×${PER_MIB}（停掉该卡上占显存的进程后再试；本脚本不 kill）"; return 3; }
  fi
  for p in "$@"; do
    up "$p" && { echo "ALREADY_UP :$p"; continue; }
    cd "$B" && env VQA_GPUS="$GPU" VQA_FORCE_GPU="$GPU" VQA_DEDICATED=1 VQA_PORT="$p" VQA_COMFY= HF_HOME="$B/hf" PYTHONUNBUFFERED=1 \
      VQA_HB="/root/work/fredw/gpu_heartbeats/VQA-$HOST-$p.json" setsid nohup "$B/venv/bin/python" -u "$B/server.py" </dev/null >>"$B/logs/server_$p.log" 2>&1 &
    echo $! > "$B/server_$p.pid"; echo "started instance :$p pid $!（GPU$GPU）"
    sleep "${VQA_STAGGER_S:-25}"                # 错开加载峰值
  done
  return 0
}

start_router() {
  if up "$ROUTER"; then echo "router :$ROUTER already up"; return 0; fi
  cd "$B" && env VQA_PORT="$ROUTER" VQA_BACKENDS="$(echo $PORTS | tr ' ' ,)" NS_SCORE_THREADS=4 PYTHONUNBUFFERED=1 \
    setsid nohup "$B/venv/bin/python" -u "$B/vqa_router.py" </dev/null >>"$B/logs/router_$ROUTER.log" 2>&1 &
  echo $! > "$B/router_$ROUTER.pid"; echo "started router :$ROUTER → $PORTS pid $!"
}

case "$CMD" in
  status) health; exit 0;;
  health) health; exit $?;;
  stop)
    [ -f "$B/router_$ROUTER.pid" ] && { kill "$(cat "$B/router_$ROUTER.pid")" 2>/dev/null && echo "stopped router"; rm -f "$B/router_$ROUTER.pid"; }
    stop_ports $PORTS; exit 0;;
  anomaly)
    [ -n "${ANOMALY_PY:-}" ] || { echo "SET ANOMALY_PY=<有 ultralytics/insightface/onnxruntime 的 python>（gpu33 上未核；没有就不起，accept 退回 count_host）"; exit 1; }
    up 8893 && { echo "ALREADY_UP :8893"; exit 0; }
    CR=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8-sig"))["hosts"][sys.argv[2]]["comfy_root"])' "$REPO/config/factory/hosts.json" "$HOST")
    mkdir -p "$B/logs"
    cd "$REPO" && env CUDA_VISIBLE_DEVICES="" ANOMALY_PORT=8893 ANOMALY_COMFY_ROOT="$CR" OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 NS_SCORE_THREADS=8 PYTHONUNBUFFERED=1 \
      setsid nohup nice -n 10 "$ANOMALY_PY" -u tools/vqa/anomaly_server.py </dev/null >>"$B/logs/anomaly_8893.log" 2>&1 &
    echo $! > "$B/anomaly_8893.pid"; sleep 20; hjson 8893; echo; exit 0;;
  scale)
    K=${OPT:-}
    case "$K" in ''|*[!0-9]*) echo "usage: $0 scale K（0 ≤ K ≤ $N）"; exit 1;; esac
    [ "$K" -le "$N" ] || K=$N
    keep=""; drop=""; i=0
    for p in $PORTS; do if [ "$i" -lt "$K" ]; then keep="$keep $p"; else drop="$drop $p"; fi; i=$((i+1)); done
    echo "scale → keep [$keep ] drop [$drop ]"
    [ -n "$drop" ] && stop_ports $drop
    rc=0
    if [ -n "$keep" ]; then start_instances $keep || rc=$?; fi
    [ "$rc" = 0 ] && start_router
    sleep "${VQA_SETTLE_S:-30}"; health "$K"; hrc=$?
    [ "$rc" = 0 ] || exit $rc
    exit $hrc;;
  start) ;;
  *) echo "usage: $0 start [--replace] | scale K | health | status | stop | anomaly"; exit 1;;
esac

# ---- start
[ "$ENABLED" = 1 ] || echo "WARN lane_roles.enabled=false（照起，但调度仍旧行为）"
r=$(hjson "$ROUTER")
if [ -n "$r" ] && ! printf '%s' "$r" | grep -q '"gpu": *"router"'; then
  if [ "$OPT" = "--replace" ] && [ -f "$B/server_$ROUTER.pid" ]; then
    kill "$(cat "$B/server_$ROUTER.pid")" 2>/dev/null; rm -f "$B/server_$ROUTER.pid"; echo "replaced old single instance :$ROUTER"; sleep 5
  else
    echo "PORT_BUSY :$ROUTER 上是旧单实例（start_gpu33_vqa.sh）；用 start --replace 先停它（只认 $B/server_$ROUTER.pid）"; exit 4
  fi
fi
start_instances $PORTS || exit $?
start_router
sleep 45; health
