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
# W-INFRA 11-06：本机身份 = OFFLINE_SELF → hosts.json hostname 映射（gpu33 真实主机名 gpu3、gpu36 是 gpu6；tools/factory/hosts.py self）→ hostname -s
SELF=${OFFLINE_SELF:-$(python3 "$REPO/tools/factory/hosts.py" self "$(hostname -s 2>/dev/null)" 2>/dev/null)}; SELF=${SELF:-$(hostname -s)}
if [ "$SELF" != "$HOST" ] && [ "${FORCE:-0}" != 1 ]; then echo "WRONG_HOST 本机=$SELF 审图位=$HOST（FORCE=1 可越过）"; exit 2; fi
PER_MIB=${VQA_PEAK_MIB:-7500}          # config/vqa.json model.vram_budget：nf4 实例峰值 7206–7386 MiB
COMFY_PORT=$((8188 + GPU))
HB_DIR=${VQA_HB_DIR:-/root/work/fredw/gpu_heartbeats}
PROC=${VQA_PROC:-/proc}

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

start_instances() {   # $@ = 要保证在跑的实例端口；显存不够先让该卡 ComfyUI 卸模型；仍放不下全部 → 放得下几个起几个（≥1）、返回 5（W-INFRA 11-06）；
  # 一个都放不下退出 3（不 kill 别人）。分发器按 /health 用活着的实例，少起几个不影响调度；scale 钩子失败重试时再补
  [ -x "$B/venv/bin/python" ] || { echo "NO_VENV $B/venv（先跑 tools/vqa/deploy_offline.sh gpu33）"; return 1; }
  [ -f "$B/models/Qwen3-VL-8B-Instruct/config.json" ] || { echo "NO_MODEL $B/models/Qwen3-VL-8B-Instruct"; return 1; }
  cp "$REPO/tools/vqa/server.py" "$REPO/tools/vqa/vqa_router.py" "$REPO/config/vqa.json" "$B/" || { echo "COPY_FAIL"; return 1; }
  mkdir -p "$B/logs" "$HB_DIR"
  need=0; for p in "$@"; do up "$p" || need=$((need+1)); done
  fit=$need
  if [ "$need" -gt 0 ]; then
    FREE=$(nvidia-smi -i "$GPU" --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
    if [ "${FREE:-0}" -lt $((need * PER_MIB)) ]; then      # 该卡 ComfyUI（审图位 / 视频段刚出完视频）卸模型后再量一次；仍不够就只起放得下的，不 kill
      curl -s -m 10 -X POST "http://127.0.0.1:$COMFY_PORT/free" -H 'Content-Type: application/json' -d '{"unload_models":true,"free_memory":true}' >/dev/null 2>&1
      sleep "${VQA_FREE_WAIT_S:-5}"; FREE=$(nvidia-smi -i "$GPU" --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
    fi
    fit=$(( ${FREE:-0} / PER_MIB )); [ "$fit" -gt "$need" ] && fit=$need
    [ "$fit" -ge 1 ] || { echo "VRAM_TOO_LOW GPU$GPU free=${FREE}MiB < 1×${PER_MIB}（停掉该卡上占显存的进程后再试；本脚本不 kill）"; return 3; }
    [ "$fit" -lt "$need" ] && echo "VRAM_PARTIAL GPU$GPU free=${FREE}MiB 放得下 $fit/$need 个实例：先起 $fit 个（分发器用活着的），其余等显存"
  fi
  started=0
  for p in "$@"; do
    up "$p" && { echo "ALREADY_UP :$p"; continue; }
    [ "$started" -lt "$fit" ] || { echo "SKIP :$p（显存不够，本轮不起）"; continue; }
    cd "$B" && env VQA_GPUS="$GPU" VQA_FORCE_GPU="$GPU" VQA_DEDICATED=1 VQA_PORT="$p" VQA_COMFY= HF_HOME="$B/hf" PYTHONUNBUFFERED=1 \
      VQA_HB="$HB_DIR/VQA-$HOST-$p.json" setsid nohup "$B/venv/bin/python" -u "$B/server.py" </dev/null >>"$B/logs/server_$p.log" 2>&1 &
    echo $! > "$B/server_$p.pid"; echo "started instance :$p pid $!（GPU$GPU）"
    started=$((started+1))
    sleep "${VQA_STAGGER_S:-25}"                # 错开加载峰值
  done
  [ "$fit" -lt "$need" ] && return 5
  return 0
}

is_router() { printf '%s' "$(hjson "$ROUTER")" | grep -q '"gpu": *"router"'; }
loaded() { hjson "$1" 2 2>/dev/null | grep -q '"loaded": *true'; }

start_router() {
  if up "$ROUTER"; then
    is_router && { echo "router :$ROUTER already up"; return 0; }
    echo "PORT_BUSY :$ROUTER 上是旧单实例，分发器起不了 → 用 handover 交接（start --replace 同义）"; return 4
  fi
  cd "$B" && env VQA_PORT="$ROUTER" VQA_BACKENDS="$(echo $PORTS | tr ' ' ,)" NS_SCORE_THREADS=4 PYTHONUNBUFFERED=1 \
    setsid nohup "$B/venv/bin/python" -u "$B/vqa_router.py" </dev/null >>"$B/logs/router_$ROUTER.log" 2>&1 &
  echo $! > "$B/router_$ROUTER.pid"; echo "started router :$ROUTER → $PORTS pid $!"
}

is_server_py() { tr '\0' ' ' < "$PROC/$1/cmdline" 2>/dev/null | grep -q "server.py"; }   # 这个 pid 是本仓库看图 server.py 吗

old_single_pid() {   # :ROUTER 上的全部监听进程（ss；Fable 复审：10.0.0.33:8870 的内网代理 lan_proxy.py 也听这个口），只认命令行是 server.py 的那个
  for pid in $(ss -ltnp 2>/dev/null | grep -E "[:.]$ROUTER +" | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u); do
    is_server_py "$pid" && { echo "$pid"; return 0; }
  done
  return 1
}

adopt_old_single() {   # 返回 0 = :ROUTER 上是旧单实例且 pid 文件在手；1 = :ROUTER 没人 / 已是分发器；2 = 有人但不是我们的进程
  r=$(hjson "$ROUTER"); [ -n "$r" ] || return 1
  printf '%s' "$r" | grep -q '"gpu": *"router"' && return 1
  f="$B/server_$ROUTER.pid"
  if [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null; then       # pid 文件在、进程在：还要是 server.py 才算（pid 复用 → 当文件失效，按监听端口重认）
    is_server_py "$(cat "$f")" && return 0
    echo "STALE_PIDFILE $f pid $(cat "$f") 不是 server.py（pid 复用），重认"; rm -f "$f"
  fi
  # 11-06 实况：start --replace 杀了 pid 文件里一个已不在的 pid、又把文件删了，旧单实例（start_gpu33_vqa.sh 起的）还在跑 → 按监听端口认回来
  pid=$(old_single_pid) || { echo "OLD_SINGLE_UNKNOWN :$ROUTER 上的进程不是本仓库 server.py（或没有 ss），不碰"; return 2; }
  echo "$pid" > "$f"; echo "ADOPT old single :$ROUTER pid $pid（按监听端口认回 pid 文件）"; return 0
}

warm() {   # 让实例真加载：发一条不带图的文本小单（server.py 里 load.lock 互斥 + 二次量显存）；成功 = /health loaded=true
  p=$1
  loaded "$p" && { echo "LOADED :$p"; return 0; }
  FREE=$(nvidia-smi -i "$GPU" --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
  if [ "${FREE:-0}" -lt "$PER_MIB" ]; then        # Fable 复审：实例早就在跑时 start_instances need=0 不会碰 ComfyUI，这里也要先让该卡 ComfyUI 卸模型再量
    curl -s -m 10 -X POST "http://127.0.0.1:$COMFY_PORT/free" -H 'Content-Type: application/json' -d '{"unload_models":true,"free_memory":true}' >/dev/null 2>&1
    sleep "${VQA_FREE_WAIT_S:-5}"; FREE=$(nvidia-smi -i "$GPU" --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
  fi
  [ "${FREE:-0}" -ge "$PER_MIB" ] || { echo "WARM_SKIP :$p 显存 ${FREE}MiB < $PER_MIB（ComfyUI 卸模型后仍不够：不加载，免得 OOM）"; return 3; }
  curl -s -m "${VQA_WARM_S:-600}" -X POST "http://127.0.0.1:$p/generate" -H 'Content-Type: application/json' \
    -d '{"text":"ok","images":[],"max_new_tokens":1,"wait_s":90,"label":"warm"}' >/dev/null 2>&1
  loaded "$p" && { echo "WARMED :$p"; return 0; }
  echo "WARM_FAIL :$p $(hjson "$p" | head -c 160)"; return 4
}

warm_all() {   # 按顺序预热在跑的实例；显存不够的后面几个：未加载的停掉（只停 pid 文件里的），免得来单就加载把卡撑爆；→ 已加载个数
  nload=0
  for p in $PORTS; do
    up "$p" || continue
    if warm "$p"; then nload=$((nload+1)); else stop_ports "$p"; fi
  done
  echo "loaded instances: $nload"
}

handover() {
  # W-INFRA 11-06（PS-MASTER 实况：gpu33:3 旧单实例 6.5 GB 还占 :8870、3 个懒加载实例在跑、分发器起不了 → 谁来单谁加载 → OOM）。确定性交接：
  # ① 认回旧单实例 pid 文件（只认 server.py）② 按显存起放得下的实例（算上旧单实例占的）③ 逐个预热，放不下的停掉
  # ④ ≥1 个加载好 → 停旧单实例 → 等 :8870 空（≤30 s，不强杀）→ 起分发器 ⑤ 显存松了再补实例、再预热 ⑥ health。失败在哪一步就停在哪一步，旧单实例不先停
  adopt_old_single; arc=$?
  [ "$arc" = 2 ] && return 6
  HAD_OLD=0; [ "$arc" = 0 ] && HAD_OLD=1
  start_instances $PORTS; SRC=$?
  case "$SRC" in 0|5) ;; *) return $SRC;; esac
  warm_all
  if [ "$HAD_OLD" = 1 ]; then
    [ "$nload" -ge 1 ] || { echo "HANDOVER_HOLD 没有一个新实例加载成功：旧单实例 :$ROUTER 留着继续服务"; return 7; }
    opid=$(cat "$B/server_$ROUTER.pid")
    kill "$opid" 2>/dev/null; rm -f "$B/server_$ROUTER.pid"
    echo "$(date '+%F %T') retired old single :$ROUTER pid $opid（loaded instances=$nload）" >> "$B/retired_$ROUTER.log"
    echo "retired old single :$ROUTER pid $opid"
    for i in $(seq 1 30); do up "$ROUTER" || break; sleep 1; done
    up "$ROUTER" && { echo "OLD_STILL_LISTENING :$ROUTER 30 s 没退出，不起分发器（本脚本不强杀）"; return 8; }
    sleep "${VQA_FREE_WAIT_S:-5}"
  fi
  start_router || return $?
  start_instances $PORTS; SRC=$?           # 旧单实例的显存回来了：能补几个补几个
  case "$SRC" in 0|5) ;; *) return $SRC;; esac
  warm_all
  sleep "${VQA_SETTLE_S:-10}"; health; hrc=$?
  [ "$nload" -ge 1 ] || return 7
  return $hrc
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
    SRC=0                                            # 起实例的结果（别叫 rc：health() 里的 rc 是全局变量，会盖掉）
    if [ -n "$keep" ]; then start_instances $keep || SRC=$?; fi
    RRC=0; case "$SRC" in 0|5) start_router || RRC=$?;; esac   # 5 = 显存只够部分实例：分发器照起、用活着的（W-INFRA 11-06）
    sleep "${VQA_SETTLE_S:-30}"; health "$K"; hrc=$?
    [ "$SRC" = 0 ] || exit $SRC
    [ "$RRC" = 0 ] || exit $RRC                     # 4 = :8870 上是旧单实例（PORT_BUSY）：退出码说明原因，钩子日志能看懂
    exit $hrc;;
  handover) handover; exit $?;;
  start) ;;
  *) echo "usage: $0 start [--replace] | handover | scale K | health | status | stop | anomaly"; exit 1;;
esac

# ---- start
[ "$ENABLED" = 1 ] || echo "WARN lane_roles.enabled=false（照起，但调度仍旧行为）"
r=$(hjson "$ROUTER")
if [ -n "$r" ] && ! printf '%s' "$r" | grep -q '"gpu": *"router"'; then
  if [ "$OPT" = "--replace" ]; then       # W-INFRA 11-06：以前这里先杀旧单实例再起实例 → 实例显存不够、分发器也没起、看图停摆；改为确定性交接
    handover; exit $?
  fi
  echo "PORT_BUSY :$ROUTER 上是旧单实例（start_gpu33_vqa.sh）；用 handover（= start --replace）交接：先起 + 预热新实例，再停旧的、换分发器"; exit 4
fi
start_instances $PORTS; SRC=$?
case "$SRC" in 0|5) ;; *) exit $SRC;; esac     # 5 = 显存只够部分实例：照起分发器、用活着的，最后以 5 退出（W-INFRA 11-06）
start_router
sleep "${VQA_SETTLE_S:-45}"; health; hrc=$?
[ "$SRC" = 0 ] || exit $SRC
exit $hrc
