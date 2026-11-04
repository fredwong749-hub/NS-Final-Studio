#!/bin/bash
# FACTORY（总调度 11-02 20:4x）：VQAGATE 的常驻人数检测服务 tools/vqa/anomaly_server.py，只在 gpu36。
# W40（11-04 02:2x）：原来写死 GPU2（gpu36:2 坏卡红线） → 改成 ANOMALY_GPU（默认 1，W38 02:1x 实测可用），给 2 直接拒绝退出。
#   resident_sync.vqa_tick 每 5 分钟探 127.0.0.1:8893/health，不在就按同一口径（config/vqa.json anomaly.gpu，默认 1）补起，不调本脚本。
# 只听 127.0.0.1:8893；内网入口 tools/netfix/lan_proxy.py 绑 10.0.0.36:8893、只放行 10.0.0.33（自有机器内网，L-128）。
# 单实例：pid 文件里的外层保活循环活着就不再起；崩溃 / 409（代码换了）后 5 s 按部署版代码重启；每次拉起追加一行事件。不删任何文件。
# 心跳：GET 127.0.0.1:8893/health（loaded / mirror_seg / code_sha），SENTINEL 按它判掉线。
# 用法（服务器上，仓库目录）：bash ops/factory/anomaly_resident.sh gpu36 [start|stop|status]
set -u
export TZ=Asia/Tokyo
SELF=$1; CMD=${2:-start}
[ "$SELF" = gpu36 ] || { echo "anomaly_resident: 只在 gpu36"; exit 0; }
GPU=${ANOMALY_GPU:-1}
[ "$GPU" = 2 ] && { echo "anomaly_resident: 拒绝 GPU2（gpu36:2 坏卡红线），改用 ANOMALY_GPU=0/1"; exit 3; }
PROD=/root/work/fredw/offline_20261101/repo; PY=/root/work/fredw/venv/bin/python
BASE=/root/work/fredw/factory; mkdir -p $BASE/run $BASE/logs
PIDF=$BASE/run/anomaly_resident.pid; PXF=$BASE/run/anomaly_lan_proxy.pid
LOG=$BASE/logs/anomaly_resident.log; EV=$BASE/logs/anomaly_resident_events.jsonl; PORT=8893
alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }
case "$CMD" in
  status) alive $PIDF && echo "anomaly_resident pid $(cat $PIDF) alive" || echo "anomaly_resident DEAD"
          alive $PXF && echo "lan_proxy pid $(cat $PXF) alive" || echo "lan_proxy DEAD"; curl -s -m10 127.0.0.1:$PORT/health; echo; exit 0;;
  stop) for f in $PIDF $PXF; do alive $f && { pkill -TERM -P "$(cat $f)"; kill -TERM "$(cat $f)"; echo "stopped $(cat $f)"; }; done; exit 0;;
esac
if ! alive $PIDF; then
  setsid nohup bash -c "
    why=boot
    while true; do
      echo \"{\\\"kind\\\": \\\"anomaly_resident\\\", \\\"host\\\": \\\"$SELF\\\", \\\"at\\\": \\\"\$(date -Iseconds)\\\", \\\"reason\\\": \\\"\$why\\\", \\\"port\\\": $PORT}\" >> $EV
      cd $PROD && CUDA_VISIBLE_DEVICES=$GPU CUDA_DEVICE_ORDER=PCI_BUS_ID ANOMALY_PORT=$PORT ANOMALY_COMFY_ROOT=/root/work/fredw/comfy \
        NS_SCORE_THREADS=4 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 nice -n 5 $PY -u tools/vqa/anomaly_server.py
      rc=\$?; echo \"\$(date -Is) anomaly_server exited rc=\$rc，5 s 后重启\"; why=\"exit_rc_\$rc\"; sleep 5
    done" </dev/null >>$LOG 2>&1 &
  echo $! > $PIDF
  echo "anomaly_resident started pid $(cat $PIDF) port $PORT"
else
  echo "anomaly_resident already alive pid $(cat $PIDF)"
fi
if ! alive $PXF; then
  setsid nohup bash -c "cd $PROD; while true; do python3 tools/netfix/lan_proxy.py --bind 10.0.0.36 --port $PORT --allow 10.0.0.33 --target 127.0.0.1:$PORT; sleep 5; done" \
    </dev/null >>$BASE/logs/anomaly_lan_proxy.log 2>&1 &
  echo $! > $PXF
  echo "lan_proxy started pid $(cat $PXF) 10.0.0.36:$PORT → 127.0.0.1:$PORT（只放行 10.0.0.33）"
fi
