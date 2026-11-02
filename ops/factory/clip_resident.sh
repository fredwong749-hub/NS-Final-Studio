#!/bin/bash
# FACTORY D6（K-OPS-F04，总调度 11-02 01:5x）：本机常驻 CLIP 打分服务（tools/gen_contract/clip_srv.py --serve），只听 127.0.0.1:8872。
# 起因：gpu36 上 clip_srv 每单冷启动、空闲显存 < 8000 MB 就退 CPU，一单 88.9 s（11-02 01:46 实测）；常驻后模型只加载一次。
# gpu36：CPU 常驻（GPU2 显存全部让给看图）。gpu33（总调度 11-02 15:4x）：原来每单临时起 clip_srv 子进程，15:18 同时 4 个、load 300 →
#   常驻钉 GPU1（出图道之一，空闲约 10 GB；CLIP-L 约 1.7 GB；OOM 时 clip_srv 自己先让、再退 CPU 子进程）；GPU2 坏卡永不用。
#   线程按 K-OPS-F17：8 线程、nice 10、绑最后 16 核（80-95），不和出图 / producer 抢 CPU。
# 幂等：已在跑就不动。保活：外层循环，409（代码换了）/ 崩溃后 3 s 按仓库最新代码重启。不删任何文件。
# 线程：常驻单进程（不是按片子反复起的脚本），CPU 模式给 16 线程（96 核机；4 线程时 CLIP-L 一单 83 s，11-02 08:5x 实测）
# 用法（服务器上）：bash ops/factory/clip_resident.sh gpu36 [status|stop]
set -u
export TZ=Asia/Tokyo
SELF=$1; CMD=${2:-start}
OFF=/root/work/fredw/offline_20261101; PROD=$OFF/repo; RL=/root/work/fredw/reflock
BASE=/root/work/fredw/factory; mkdir -p $BASE/run $BASE/logs
PIDF=$BASE/run/clip_resident.pid; LOG=$BASE/logs/clip_resident.log; EV=$BASE/logs/clip_resident_events.jsonl; PORT=${NS_CLIP_SRV_PORT:-8872}
alive() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }
case "$CMD" in
  status) alive && echo "clip_resident pid $(cat $PIDF) alive" || echo "clip_resident DEAD"; curl -s -m3 127.0.0.1:$PORT/health; echo; exit 0;;
  stop) alive && { pkill -TERM -P "$(cat $PIDF)"; kill -TERM "$(cat $PIDF)"; echo stopped; } || echo "not running"; exit 0;;
esac
case $SELF in
  gpu36) GPU=""; DEV=cpu; TH=16; NICE=5; CPUS=""; PY=/root/work/fredw/venv/bin/python;;   # 总调度 11-02 07:5x：改 CPU 常驻，GPU2 显存全部让给看图（VQAGATE 3 实例）
  gpu33) GPU=1; DEV=cuda; TH=8; NICE=10; CPUS=80-95; PY=/root/claude-kimi-ns-studio-v1/env/comfy/bin/python;;   # 总调度 11-02 15:4x
  *) echo "clip_resident: $SELF 未配置"; exit 0;;
esac
alive && { echo "clip_resident already alive pid $(cat $PIDF)"; exit 0; }
# 每次拉起追加一行事件（WORKFLOW 11-02：kind=clip_resident、host、时间、原因；排查打分慢 / 断时与 producer 重启放一起看）
setsid nohup bash -c "
  why=boot
  while true; do
    echo \"{\\\"kind\\\": \\\"clip_resident\\\", \\\"host\\\": \\\"$SELF\\\", \\\"at\\\": \\\"\$(date -Iseconds)\\\", \\\"reason\\\": \\\"\$why\\\", \\\"gpu\\\": \\\"$DEV$GPU\\\", \\\"port\\\": $PORT}\" >> $EV
    cp -a $PROD/tools/gen_contract/clip_srv.py $RL/clip_srv.py
    cp -a $PROD/services/agent/ns_agent/gen_contract/metrics.py $RL/metrics.py
    cd $RL && NS_CLIP_CODE_SRC=$PROD CUDA_VISIBLE_DEVICES=$GPU NS_CLIP_DEVICE=$DEV NS_CLIP_PATH=$RL/clip-vit-large-patch14 \
      OMP_NUM_THREADS=$TH MKL_NUM_THREADS=$TH OPENBLAS_NUM_THREADS=$TH NUMEXPR_NUM_THREADS=$TH NS_SCORE_THREADS=$TH TZ=Asia/Tokyo \
      nice -n $NICE ${CPUS:+taskset -c $CPUS} $PY -u clip_srv.py --serve $PORT
    rc=\$?; echo \"\$(date -Is) clip_srv exited rc=\$rc，3 s 后重启\"; why=\"exit_rc_\$rc\"; sleep 3
  done" </dev/null >>$LOG 2>&1 &
echo $! > $PIDF
sleep 1; echo "clip_resident started pid $(cat $PIDF) port $PORT gpu $GPU"
