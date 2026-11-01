#!/bin/bash
# offline_20261101：笔记本回来后执行（Git Bash）：bash "/d/NS-Final Studio/ops/offline/resume_from_gpu33.sh"
#  1) 停 gpu33 / gpu36 上的离线循环（只停 /root/work/fredw/offline_20261101/run/*.pid 里自己的进程）
#  2) 拉回冻结（FREEZE_TS）之后服务器上改过的文件 → data/_offline_pull/<host>/，再按 merge_pull.py 并回（新者为准、不删笔记本文件、共享文件按对象合并）
#  3) 笔记本 producer 解除暂停并启动 serve；启动 night.py
#  4) data_parity（只读检查）
# 日志：ops/logs/resume_from_gpu33.log
ROOT="/d/NS-Final Studio"
OFF=/root/work/fredw/offline_20261101
LOG="$ROOT/ops/logs/resume_from_gpu33.log"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=30 -o ServerAliveInterval=15 -o ServerAliveCountMax=3"
mkdir -p "$ROOT/ops/logs" "$ROOT/data/_offline_pull"
exec > >(tee -a "$LOG") 2>&1
date "+%F %T resume start"
cd "$ROOT" || exit 1

echo "== 1) 停服务器离线循环"
for h in gpu33 gpu36; do
  $SSH $h "bash $OFF/stop.sh" || { echo "!! $h 停不下来（连不上？）——不继续，免得两边各跑一套"; exit 1; }
  # VQA 看图复核 watcher（run/vqa.pid，VQA 11-01 加）：stop.sh 漏掉也在这里停；本地看图服务（/root/work/fredw/vqa/server.pid）留着，笔记本回来后接着用
  $SSH $h "P=$OFF/run/vqa.pid; [ -f \$P ] && kill \$(cat \$P) 2>/dev/null; rm -f \$P; echo vqa watcher stopped" || true
done

echo "== 2) 拉回冻结后改过的文件"
for h in gpu33 gpu36; do
  mkdir -p "data/_offline_pull/$h"
  $SSH $h "cd $OFF/repo && F=\$(cat $OFF/FREEZE_TS) && find data -type f -newermt @\$F ! -name '*.tmp' ! -path 'data/producer/leases/*' -print0 | tar cf - --null -T -" \
    | tar xf - -C "data/_offline_pull/$h" || { echo "!! $h 拉回失败，未合并，笔记本数据没动"; exit 1; }
  echo "$h 拉回 $(find "data/_offline_pull/$h" -type f | wc -l) 个文件"
done
.venv/Scripts/python.exe ops/offline/merge_pull.py || { echo "!! 合并失败（原文件在 data/_offline_pull/_backup）"; exit 1; }

echo "== 2b) 依赖自检（K-OPS-W02：资产图读得全、配音解释器、声音表系列；fail 只报警不中断，按清单修）"
PYTHONUTF8=1 .venv/Scripts/python.exe tools/pipeline/remote_preflight.py || echo "!! 依赖自检有 fail，见 data/autopilot/remote_preflight/latest.json"

echo "== 3) 重启笔记本 producer + night.py"
PYTHONUTF8=1 .venv/Scripts/python.exe tools/autopilot/producer.py resume --by OFFLINE-resume --note "离线结束，gpu33/gpu36 数据已并回"
powershell.exe -NoProfile -Command "\$r='D:\NS-Final Studio'; \$env:PYTHONUTF8='1'; Start-Process -WindowStyle Hidden -WorkingDirectory \$r -FilePath (Join-Path \$r '.venv\Scripts\python.exe') -ArgumentList '-u','tools/autopilot/producer.py','serve' -RedirectStandardOutput (Join-Path \$r 'ops\logs\producer.out.log') -RedirectStandardError (Join-Path \$r 'ops\logs\producer.err.log'); Start-Process -WindowStyle Hidden -WorkingDirectory \$r -FilePath (Join-Path \$r '.venv\Scripts\python.exe') -ArgumentList '-u','tools/series10_video/night.py' -RedirectStandardOutput (Join-Path \$r 'data\pipeline\runs\series10_v1\video\night.out') -RedirectStandardError (Join-Path \$r 'data\pipeline\runs\series10_v1\video\night.err')"
sleep 30
cat data/producer/heartbeat.json; echo; tail -2 data/pipeline/runs/series10_v1/video/night.log

echo "== 4) data_parity"
PYTHONUTF8=1 .venv/Scripts/python.exe tools/qa/data_parity.py || echo "!! data_parity 有不一致，见上"
date "+%F %T resume done"
