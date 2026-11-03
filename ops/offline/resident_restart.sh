#!/bin/bash
# 服务器常驻生产：热重启本机 producer（+ night）（WORKFLOW 11-01，K-OPS-W07）。不暂停 producer（stop.sh 会暂停，这里不用它）。
# 用法：bash resident_restart.sh gpu33|gpu36 [producer-only]
#   producer-only：只起 fwd + producer（出图侧），night 不起——总调度 18:23：night 等 jobs.json 按 L-088 在服务器上重编后再起
# 只停 run/*.pid 里、命令行对得上的自己的进程。
set -u
SELF=$1; MODE=${2:-all}; OFF=/root/work/fredw/offline_20261101
R=$OFF/repo
# PRODMERGE-O 11-03（PLAN_V2_MASTER v4 1-5）：按剧起——RUN = 本机 runs.json 的 primary（当前剧唯一来源），producer / night 都带 --run；
# 读不到 = 不起（失败关闭，不回退 V1）。视觉模型目录用发版部署目录 $R/models_cache/vision（video10_srv 退役）
RUN=$($OFF/venv/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("primary") or "")' $R/config/pipeline/runs.json 2>/dev/null)
[ -n "$RUN" ] || [ "$MODE" = "all" ] || { echo "runs.json 读不到 primary：不起 producer / night（失败关闭）"; exit 2; }
VISION=$R/models_cache/vision
# 第二季等额外剧的 producer（ensure_runs.sh，K-OPS-W25）：night-only 以外的模式先停、最后再按 runs.json 起
[ "$MODE" != "night-only" ] && bash $R/ops/offline/ensure_runs.sh $SELF stop
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
  export NS_QC_VISION_DIR=$VISION
  alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }
  alive $OFF/run/fwd.pid      || { setsid nohup $OFF/venv/bin/python -u $OFF/fwd.py </dev/null >>$OFF/logs/fwd.out 2>&1 & echo $! >$OFF/run/fwd.pid; }
  sleep 1
  alive $OFF/run/producer.pid || { setsid nohup $OFF/venv/bin/python -u tools/autopilot/producer.py serve --run $RUN </dev/null >>$OFF/logs/producer.out 2>&1 & echo $! >$OFF/run/producer.pid; }
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
  export NS_QC_VISION_DIR=$VISION
  alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }
  alive $OFF/run/fwd.pid   || { setsid nohup $OFF/venv/bin/python -u $OFF/fwd.py </dev/null >>$OFF/logs/fwd.out 2>&1 & echo $! >$OFF/run/fwd.pid; }
  sleep 1
  alive $OFF/run/night.pid || { setsid nohup $OFF/venv/bin/python -u tools/series10_video/night.py --run $RUN </dev/null >>$OFF/logs/night.out 2>&1 & echo $! >$OFF/run/night.pid; }
  sleep 3
  for n in fwd night; do echo "$n pid $(cat $OFF/run/$n.pid) $(alive $OFF/run/$n.pid && echo alive || echo DEAD)"; done
  echo "producer not started (night-only：出图归笔记本)"
else
  bash $OFF/start.sh $SELF
fi
[ "$MODE" != "night-only" ] && bash $R/ops/offline/ensure_runs.sh $SELF
