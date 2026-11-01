#!/bin/bash
# NETFIX 验收取证：每 5 分钟看两台服务器常驻 producer 日志里 SINCE 之后的 dispatch / rendered / passed（K-OPS-N04 第一次真派单）。
# 用法：bash tools/netfix/watch_server_dispatch.sh 2026-11-01T23:10   每台每轮输出一行计数；见到 passed 后打印证据行并退出。
SINCE=${1:-2026-11-01T23:10}
OFF=/root/work/fredw/offline_20261101
while true; do
  done_all=1
  for h in gpu33 gpu36; do
    out=$(timeout 120 ssh -o BatchMode=yes -o ConnectTimeout=30 $h "f=$OFF/logs/producer.out; p=\$(cat $OFF/run/producer.pid 2>/dev/null); a=\$(kill -0 \$p 2>/dev/null && echo alive || echo dead); awk -v s='$SINCE' 'substr(\$0,1,16)>=s' \$f 2>/dev/null > /tmp/nsnetfix_tail.txt; echo \"\$a d=\$(grep -c ' dispatch ' /tmp/nsnetfix_tail.txt) r=\$(grep -c ' rendered ' /tmp/nsnetfix_tail.txt) p=\$(grep -c ' passed ' /tmp/nsnetfix_tail.txt)\"; grep -m2 ' passed ' /tmp/nsnetfix_tail.txt | cut -c1-300" 2>&1)
    echo "$(date '+%H:%M') $h $(echo "$out" | head -1)"
    if echo "$out" | head -1 | grep -q ' p=[1-9]'; then echo "EVIDENCE $h"; echo "$out" | tail -n +2; else done_all=0; fi
  done
  [ $done_all = 1 ] && exit 0
  sleep 300
done
