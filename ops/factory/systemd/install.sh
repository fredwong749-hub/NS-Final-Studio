#!/bin/bash
# FACTORY L-105（项目方 11-02 03:1x：“允许服务器常驻托管”；K-OPS-F10）：把仓库里的 systemd --user 单元装到本机（随 sv 发版，不在服务器上手写）。
# 只安装 + enable，不 start、不停 nohup 进程——切换由 switch.sh 逐个服务做（不停产）。幂等。
# 用法（服务器上，repo 目录）：bash ops/factory/systemd/install.sh gpu33|gpu36
set -eu
SELF=$1
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SRC=$REPO/ops/factory/systemd
UD=$HOME/.config/systemd/user
ENVD=$HOME/work/fredw/ns_factory_systemd
mkdir -p "$UD" "$ENVD" /root/work/fredw/factory/logs /root/work/fredw/offline_20261101/logs
cp -a "$SRC/env/$SELF.env" "$ENVD/host.env"
UNITS="ns-fwd.service ns-producer.service ns-night.service"
[ "$SELF" = gpu36 ] && UNITS="$UNITS ns-clip-resident.service"      # 常驻 CLIP 只在 gpu36 GPU2（L-100）
for u in $UNITS; do cp -a "$SRC/$u" "$UD/$u"; done
loginctl enable-linger "$(id -un)" 2>/dev/null || echo "WARN: enable-linger 失败（开机自启需要它）"
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
systemctl --user daemon-reload
for u in $UNITS; do systemctl --user enable "$u" >/dev/null 2>&1 || echo "WARN: enable $u 失败"; done
echo "installed: $UNITS"
for u in $UNITS; do printf '%s %s %s\n' "$u" "$(systemctl --user is-enabled $u 2>/dev/null)" "$(systemctl --user is-active $u 2>/dev/null)"; done
