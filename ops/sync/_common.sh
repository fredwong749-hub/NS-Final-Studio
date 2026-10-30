#!/bin/bash
# Shared by ops/sync/*.sh (sourced, not run). One log + one lock per script.
#   log : D:\NS-Final Studio\ops\logs\<name>.log  (rotated to .log.1 at 5 MB)
#   lock: D:\NS-Final Studio\ops\logs\<name>.lock\ (mkdir lock; holds pid; stale only if pid dead, or pid unreadable and older than 2 h)
# If the lock is held by a live run, this run logs "skip" and exits 0.
# 封板修复：pid 活着就绝不算 stale（原 2 h 规则会给常驻的 tunnel.sh 再起一个循环抢端口，且一方 EXIT 会删掉另一方的锁）；
#           EXIT 只删仍写着本进程 pid 的锁。
# 封板修复：SSH_OPTS 给所有 ssh/scp 加保活（15 s x 3），挂死的连接约 45 s 内断开，不会一直占锁。
OPS="/d/NS-Final Studio/ops"
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=30 -o ServerAliveInterval=15 -o ServerAliveCountMax=3"
NAME=$(basename "$0" .sh)
LOG="$OPS/logs/$NAME.log"
LOCK="$OPS/logs/$NAME.lock"
mkdir -p "$OPS/logs"
if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG" 2>/dev/null || echo 0)" -gt 5242880 ]; then mv -f "$LOG" "$LOG.1"; fi
exec >>"$LOG" 2>&1
if ! mkdir "$LOCK" 2>/dev/null; then
  old=$(cat "$LOCK/pid" 2>/dev/null)
  age=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || date +%s) ))
  if [ -n "$old" ]; then
    if kill -0 "$old" 2>/dev/null; then
      date "+%F %T skip: previous run pid $old still going (${age}s)"; exit 0
    fi
  elif [ "$age" -lt 7200 ]; then
    date "+%F %T skip: lock without readable pid, only ${age}s old"; exit 0
  fi
  date "+%F %T stale lock (pid ${old:-?}, ${age}s) removed"
  rm -rf "$LOCK"; mkdir "$LOCK" || { date "+%F %T could not take lock"; exit 1; }
fi
echo $$ > "$LOCK/pid"
_release_lock() { [ "$(cat "$LOCK/pid" 2>/dev/null)" = "$$" ] && rm -rf "$LOCK"; }
trap _release_lock EXIT
date "+%F %T start $NAME (pid $$)"
