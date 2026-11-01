#!/bin/bash
# NETFIX 11-01（K-OPS-N01，总调度 fredw-2b 派）：本脚本退役。原来是“ssh 断了 30 s 重连”的 bash 循环，22:08 循环不在时 gpu36 三条隧道
# 永远修不好。现在全部转发（15180/18098/18099/18188/18189/18191 → gpu33，18288/18289/18290 → gpu36）由一个监管进程负责：
#   tools/netfix/tunnel_supervisor.py（每台服务器一条 ssh、指数退避、卡死检测、跳板恢复立刻重连、接管孤儿 ssh）。
# 任何地方还调用本脚本，都只会转去确保监管进程在跑，然后退出（不再自己起 ssh，避免和监管进程抢端口）。
# 旧版本留在 data/_quarantine/netfix_20261101/。
cd "/d/NS-Final Studio" || exit 1
PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/netfix/tunnel_supervisor.py ensure
