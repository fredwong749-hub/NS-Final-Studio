#!/bin/bash
# L-207 审图位内网入口（gpu33）：让 gpu36 上的视频打分（score_clip V9 看图）经 10.0.0.33:8870 进 gpu33 的看图分发器 127.0.0.1:8870。
# 同 tools/netfix/lan_proxy.sh（gpu36 → gpu33 方向）的反向；同一份 lan_proxy.py（只监听内网地址、只认白名单来源、无登录能力）。
# 开关 / 参数单一来源 config/pipeline/lane_roles.json review.lan_proxy = {"enabled", "bind", "port", "allow": [...], "target"}；
# enabled=false 或没配 → 本脚本不起（退出 0，打印 DISABLED）。幂等：在跑就不动；不在就拉起。保活：resident_sync 每拍 control 同步顺带跑一次（review_lan_proxy_keepalive）。
# 图片仍只在自家两台之间走（K-REV-V01：lan_url 必须 10. 内网地址，client 把关）。本脚本默认不动防火墙；--iptables 需总调度批准。
set -u
REPO=${NS_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
CFG=$REPO/config/pipeline/lane_roles.json
D=${NETFIX_DIR:-/root/work/fredw/netfix}
PY=${PY:-/usr/bin/python3}
[ -f "$CFG" ] || { echo "NO_CFG $CFG"; exit 1; }
eval "$(python3 - "$CFG" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8-sig"))
r = d.get("review") or {}
lp = r.get("lan_proxy") or {}
host = str(r.get("lane") or "gpu33:3").split(":")[0]
en = "1" if (d.get("enabled") and lp.get("enabled")) else "0"
print("ENABLED=%s; HOST=%s; BIND=%s; PORT=%s; ALLOW=%s; TARGET=%s" % (
    en, host, lp.get("bind") or "10.0.0.33", int(lp.get("port") or r.get("port_base") or 8870),
    ",".join(lp.get("allow") or ["10.0.0.36"]), lp.get("target") or ("127.0.0.1:%d" % int(r.get("port_base") or 8870))))
PY
)"
[ "$ENABLED" = 1 ] || { echo "DISABLED review.lan_proxy（config/pipeline/lane_roles.json）"; exit 0; }
# W-INFRA 11-06：本机身份 = OFFLINE_SELF → hosts.json hostname 映射（gpu33 真实主机名 gpu3；tools/factory/hosts.py self）→ hostname -s
SELF=${OFFLINE_SELF:-$(python3 "$REPO/tools/factory/hosts.py" self "$(hostname -s 2>/dev/null)" 2>/dev/null)}; SELF=${SELF:-$(hostname -s)}
if [ "$SELF" != "$HOST" ] && [ "${FORCE:-0}" != 1 ]; then echo "WRONG_HOST 本机=$SELF 审图位=$HOST"; exit 2; fi
case "$BIND" in 10.*) ;; *) echo "REFUSE bind=$BIND 不是 10. 内网地址（K-REV-V01）"; exit 2;; esac
mkdir -p "$D"
cp "$REPO/tools/netfix/lan_proxy.py" "$D/lan_proxy.py" 2>/dev/null || true
if [ "${1:-}" = "--iptables" ]; then
  for src in $(echo "$ALLOW" | tr ',' ' '); do
    iptables -C INPUT -p tcp --dport "$PORT" -s "$src" -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport "$PORT" -s "$src" -j ACCEPT
  done
  iptables -C INPUT -p tcp --dport "$PORT" ! -s 127.0.0.1 -j DROP 2>/dev/null || iptables -A INPUT -p tcp --dport "$PORT" ! -s 127.0.0.1 -j DROP
fi
PIDF=$D/review_lan_proxy.pid
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null && grep -q lan_proxy.py "/proc/$(cat "$PIDF")/cmdline" 2>/dev/null; then
  echo "review_lan_proxy alive $(cat "$PIDF") $BIND:$PORT allow=$ALLOW -> $TARGET"; exit 0
fi
setsid nohup "$PY" -u "$D/lan_proxy.py" --bind "$BIND" --port "$PORT" --allow "$ALLOW" --target "$TARGET" </dev/null >>"$D/review_lan_proxy.out" 2>&1 &
echo $! > "$PIDF"
echo "$(date '+%F %T') started $(cat "$PIDF") $BIND:$PORT allow=$ALLOW -> $TARGET" >> "$D/review_lan_proxy.log"
echo "review_lan_proxy started $(cat "$PIDF") $BIND:$PORT allow=$ALLOW -> $TARGET"
