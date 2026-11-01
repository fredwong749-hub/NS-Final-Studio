#!/bin/bash
# 服务器常驻生产：热重启本机 producer（+ night）（WORKFLOW 11-01，K-OPS-W07）。不暂停 producer（stop.sh 会暂停，这里不用它）。
# 用法：bash resident_restart.sh gpu33|gpu36 [producer-only]
#   producer-only：只起 fwd + producer（出图侧），night 不起——总调度 18:23：night 等 jobs.json 按 L-088 在服务器上重编后再起
# 只停 run/*.pid 里、命令行对得上的自己的进程。
set -u
SELF=$1; MODE=${2:-all}; OFF=/root/work/fredw/offline_20261101
R=$OFF/repo
for n in night producer; do
  f=$OFF/run/$n.pid; [ -f $f ] || continue; p=$(cat $f)
  if kill -0 $p 2>/dev/null && grep -q "night.py\|producer.py" /proc/$p/cmdline 2>/dev/null; then
    kill $p; for i in $(seq 1 15); do kill -0 $p 2>/dev/null || break; sleep 1; done
    kill -0 $p 2>/dev/null && kill -9 $p
    echo "stopped $n $p"
  fi
done
if [ "$MODE" = "producer-only" ]; then
  cd $R || exit 1
  mkdir -p $OFF/run $OFF/logs .venv/Scripts
  printf '#!/bin/sh\nexec %s/venv/bin/python "$@"\n' "$OFF" > .venv/Scripts/python.exe; chmod +x .venv/Scripts/python.exe
  rm -f $OFF/STOP
  export TZ=Asia/Tokyo OFFLINE_SELF=$SELF OFFLINE_ALIASES=$([ $SELF = gpu36 ] && echo gpu33) PATH=$OFF/bin:$PATH PYTHONUTF8=1 PYTHONIOENCODING=utf-8
  export NS_QC_VISION_DIR=/root/work/fredw/video10_srv/models_cache/vision
  alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }
  alive $OFF/run/fwd.pid      || { setsid nohup $OFF/venv/bin/python -u $OFF/fwd.py </dev/null >>$OFF/logs/fwd.out 2>&1 & echo $! >$OFF/run/fwd.pid; }
  sleep 1
  alive $OFF/run/producer.pid || { setsid nohup $OFF/venv/bin/python -u tools/autopilot/producer.py serve </dev/null >>$OFF/logs/producer.out 2>&1 & echo $! >$OFF/run/producer.pid; }
  sleep 3
  for n in fwd producer; do echo "$n pid $(cat $OFF/run/$n.pid) $(alive $OFF/run/$n.pid && echo alive || echo DEAD)"; done
  echo "night not started (producer-only)"
elif [ "$MODE" = "night-only" ]; then
  # 总调度 18:4x：服务器只跑视频（night 部署 vidgen）；出图归笔记本 producer，服务器 producer 不起
  cd $R || exit 1
  mkdir -p $OFF/run $OFF/logs .venv/Scripts
  printf '#!/bin/sh\nexec %s/venv/bin/python "$@"\n' "$OFF" > .venv/Scripts/python.exe; chmod +x .venv/Scripts/python.exe
  rm -f $OFF/STOP
  export TZ=Asia/Tokyo OFFLINE_SELF=$SELF OFFLINE_ALIASES=$([ $SELF = gpu36 ] && echo gpu33) PATH=$OFF/bin:$PATH PYTHONUTF8=1 PYTHONIOENCODING=utf-8
  export NS_QC_VISION_DIR=/root/work/fredw/video10_srv/models_cache/vision
  alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }
  alive $OFF/run/fwd.pid   || { setsid nohup $OFF/venv/bin/python -u $OFF/fwd.py </dev/null >>$OFF/logs/fwd.out 2>&1 & echo $! >$OFF/run/fwd.pid; }
  sleep 1
  alive $OFF/run/night.pid || { setsid nohup $OFF/venv/bin/python -u tools/series10_video/night.py </dev/null >>$OFF/logs/night.out 2>&1 & echo $! >$OFF/run/night.pid; }
  sleep 3
  for n in fwd night; do echo "$n pid $(cat $OFF/run/$n.pid) $(alive $OFF/run/$n.pid && echo alive || echo DEAD)"; done
  echo "producer not started (night-only：出图归笔记本)"
else
  bash $OFF/start.sh $SELF
fi
