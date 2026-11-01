#!/bin/bash
# gpu36：看图服务内网入口保活（NETFIX 11-01，K-OPS-N03）。幂等：在跑就不动；不在就拉起。
# 保活：resident_sync health（每 5 分钟经跳板）顺带跑一次本脚本；跳板断期间进程本身不依赖跳板。
# 来源白名单在 lan_proxy.py 里做（只认 10.0.0.33）。
# 可选加固（需总调度批准后再执行，本脚本默认不动防火墙 / crontab）：bash lan_proxy.sh --iptables
D=/root/work/fredw/netfix
PY=/usr/bin/python3
mkdir -p $D
if [ "${1:-}" = "--iptables" ]; then
  iptables -C INPUT -i eno3 -p tcp --dport 8870 -s 10.0.0.33 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -i eno3 -p tcp --dport 8870 -s 10.0.0.33 -j ACCEPT
  iptables -C INPUT -i eno3 -p tcp --dport 8870 -j DROP 2>/dev/null || iptables -A INPUT -i eno3 -p tcp --dport 8870 -j DROP
fi
if [ -f $D/lan_proxy.pid ] && kill -0 "$(cat $D/lan_proxy.pid)" 2>/dev/null && grep -q lan_proxy.py /proc/$(cat $D/lan_proxy.pid)/cmdline; then
  echo "lan_proxy alive $(cat $D/lan_proxy.pid)"; exit 0
fi
setsid nohup $PY -u $D/lan_proxy.py --bind 10.0.0.36 --port 8870 --allow 10.0.0.33 --target 127.0.0.1:8870 </dev/null >>$D/lan_proxy.out 2>&1 &
echo $! > $D/lan_proxy.pid
echo "$(date '+%F %T') started $(cat $D/lan_proxy.pid)" >> $D/lan_proxy.log
echo "lan_proxy started $(cat $D/lan_proxy.pid)"
