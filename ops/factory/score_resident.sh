#!/bin/bash
# AUDIT-PERF 提案 A（11-05）：本机常驻打分服务（tools/gen_contract/score_srv.py），只听 127.0.0.1；CPU，不占显存。
#   idm  8873（venv_idm：ArcFace + OCR）  hand 8874（venv_hand：mediapipe 手 / 姿态）
# 起因：full_score 每张图冷起 score_remote / hands_remote 子进程 ~40–60 s；常驻后模型只加载一次。仿 clip_resident.sh：幂等、外层循环保活
#   （409 代码换了 / 崩溃后 3 s 按仓库最新代码重启）、不删任何文件。线程 / nice / 绑核同 K-OPS-F17（8 线程、nice 10、最后 16 核）。
# 用法（服务器上）：bash ops/factory/score_resident.sh [REPO_DIR] [start|status|stop]   （REPO_DIR 缺省 = 本脚本所在仓库）
set -u
export TZ=Asia/Tokyo
REPO=${1:-$(cd "$(dirname "$0")/../.." && pwd)}; CMD=${2:-start}
BASE=${NS_SCORE_BASE:-/root/work/fredw/factory}; mkdir -p $BASE/run $BASE/logs
EV=$BASE/logs/score_resident_events.jsonl
declare -A PY=( [idm]=/root/work/fredw/venv_idm/bin/python [hand]=/root/work/fredw/venv_hand/bin/python )
declare -A PORT=( [idm]=${NS_SCORE_SRV_PORT_IDM:-8873} [hand]=${NS_SCORE_SRV_PORT_HAND:-8874} )
CPUS=${NS_SCORE_CPUSET:-80-95}; TH=${NS_SCORE_THREADS:-8}
for K in idm hand; do
  PIDF=$BASE/run/score_resident_$K.pid; LOG=$BASE/logs/score_resident_$K.log
  alive() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }
  case "$CMD" in
    status) alive && echo "score_resident_$K pid $(cat $PIDF) alive" || echo "score_resident_$K DEAD"; curl -s -m3 127.0.0.1:${PORT[$K]}/health; echo; continue;;
    stop) alive && { kill -TERM $(pgrep -P "$(cat $PIDF)") 2>/dev/null; kill -TERM "$(cat $PIDF)"; echo "stopped $K"; } || echo "$K not running"; continue;;
  esac
  alive && { echo "score_resident_$K already alive pid $(cat $PIDF)"; continue; }
  setsid nohup bash -c "
    why=boot
    while true; do
      echo \"{\\\"kind\\\": \\\"score_resident\\\", \\\"srv\\\": \\\"$K\\\", \\\"at\\\": \\\"\$(date -Iseconds)\\\", \\\"reason\\\": \\\"\$why\\\", \\\"port\\\": ${PORT[$K]}}\" >> $EV
      cd /root/work/fredw/imggen && OMP_NUM_THREADS=$TH MKL_NUM_THREADS=$TH OPENBLAS_NUM_THREADS=$TH NUMEXPR_NUM_THREADS=$TH ORT_NUM_THREADS=$TH TZ=Asia/Tokyo \
        nice -n 10 taskset -c $CPUS ${PY[$K]} -u $REPO/tools/gen_contract/score_srv.py --kind $K --serve ${PORT[$K]}
      rc=\$?; echo \"\$(date -Is) score_srv $K exited rc=\$rc，3 s 后重启\"; why=\"exit_rc_\$rc\"; sleep 3
    done" </dev/null >>$LOG 2>&1 &
  echo $! > $PIDF
  echo "score_resident_$K started pid $(cat $PIDF) port ${PORT[$K]}"
done
