#!/bin/bash
# NETFIX P0 验收：每分钟数一次笔记本到跳板的连接（Windows netstat + WSL ss）、ssh.exe 进程数、监管进程 EXIT/KILL 次数。
# 用法：bash tools/netfix/conn_watch.sh 30   → data/netfix/conn_watch.jsonl
export MSYS_NO_PATHCONV=1
N=${1:-30}; OUT="/d/NS-Final Studio/data/netfix/conn_watch.jsonl"; LOG="/d/NS-Final Studio/data/netfix/supervisor.log"
for i in $(seq 1 $N); do
  ns=$(netstat -ano -p TCP | grep "183.23.230.84:19422")
  est=$(echo "$ns" | grep -c ESTABLISHED); tw=$(echo "$ns" | grep -c TIME_WAIT); syn=$(echo "$ns" | grep -c SYN_SENT)
  wsl=$(wsl.exe -d Ubuntu-24.04 --exec bash -c "ss -tn state established dst 183.23.230.84 | tail -n +2 | wc -l" 2>/dev/null | tr -d '\r')
  sshn=$(tasklist //FI "IMAGENAME eq ssh.exe" 2>/dev/null | grep -c ssh.exe)
  ev=$(grep -c -E "EXIT|KILL" "$LOG")
  echo "{\"at\":\"$(date +%FT%T)\",\"win_est\":$est,\"win_time_wait\":$tw,\"win_syn\":$syn,\"wsl_est\":${wsl:-null},\"ssh_exe\":$sshn,\"sup_exit_kill_total\":$ev}" >> "$OUT"
  sleep 60
done
