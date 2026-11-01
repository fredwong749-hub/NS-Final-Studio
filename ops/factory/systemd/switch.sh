#!/bin/bash
# FACTORY L-105（K-OPS-F10）：把一个服务从 nohup 切到 systemd --user，不停产。
#   fwd / clip-resident：停 nohup → 立刻 start 单元（端口独占，只能先停后起；空转约 1–3 s）
#   producer：pause → 等心跳 inflight=0（≤ 90 s）→ 停 nohup → start 单元 → 心跳更新 → resume（道空转 ≤ 1 分钟）
#   night：等当前片段结束不可控 → 只在没有在途视频作业时切（首帧阶段 night 空转），否则拒绝
# 用法：bash ops/factory/systemd/switch.sh gpu33|gpu36 fwd|producer|night|clip-resident
set -u
SELF=$1; SVC=$2
OFF=/root/work/fredw/offline_20261101; R=$OFF/repo
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
set -a; . "$HOME/work/fredw/ns_factory_systemd/host.env"; set +a
PY=$OFF/venv/bin/python
alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }
stop_pid() { local f=$1; alive "$f" || return 0; local p; p=$(cat "$f"); kill "$p"; for i in $(seq 1 20); do kill -0 "$p" 2>/dev/null || break; sleep 1; done; kill -0 "$p" 2>/dev/null && kill -9 "$p"; echo "stopped nohup $(basename "$f" .pid) $p"; }
wait_active() { for i in $(seq 1 30); do [ "$(systemctl --user is-active "$1")" = active ] && { echo "$1 active after ${i}s"; return 0; }; sleep 1; done; echo "FAIL: $1 not active"; systemctl --user status "$1" --no-pager | tail -5; return 1; }
t0=$(date +%s)
case "$SVC" in
  fwd)
    stop_pid $OFF/run/fwd.pid; systemctl --user start ns-fwd.service; wait_active ns-fwd.service ;;
  clip-resident)
    P=/root/work/fredw/factory/run/clip_resident.pid
    alive $P && { pkill -TERM -P "$(cat $P)"; kill "$(cat $P)"; echo "stopped nohup clip_resident loop"; sleep 1; }
    systemctl --user start ns-clip-resident.service; wait_active ns-clip-resident.service ;;
  producer)
    cd $R
    $PY tools/autopilot/producer.py pause --by FACTORY_SYSTEMD --note "切到 systemd（L-105）" >/dev/null
    for i in $(seq 1 90); do n=$($PY -c "import json;print(json.load(open('data/producer/heartbeat.json')).get('inflight',0))" 2>/dev/null || echo 1); [ "$n" = 0 ] && break; sleep 1; done
    echo "inflight=$n after drain ${i}s"
    stop_pid $OFF/run/producer.pid
    systemctl --user start ns-producer.service; wait_active ns-producer.service || exit 1
    sleep 5; $PY tools/autopilot/producer.py resume --by FACTORY_SYSTEMD --note "已切到 systemd（L-105）" >/dev/null && echo resumed ;;
  night)
    busy=$(curl -s -m5 127.0.0.1:8190/queue 2>/dev/null | grep -c '"queue_running": \[\[' || true)
    [ "$busy" != 0 ] && { echo "REFUSE: 长镜头道有在跑的视频作业，night 现在不切"; exit 2; }
    stop_pid $OFF/run/night.pid; systemctl --user start ns-night.service; wait_active ns-night.service ;;
  *) echo "unknown service $SVC"; exit 2 ;;
esac
echo "switch $SVC done in $(( $(date +%s) - t0 ))s"
