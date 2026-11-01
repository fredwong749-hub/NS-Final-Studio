#!/bin/bash
# NETFIX P0 11-02（K-OPS-N07）：Git Bash 里的 ssh 闸门。安装 = 复制到 ~/bin/ssh（Git Bash PATH 第一位）。撤销 = 删掉 ~/bin/ssh。
# ssh 到 gpu33 / gpu36 的“命令调用”（不带 -L -R -D -W -N -M -f -S -O）改走 WSL 常驻主连接（tunnel_supervisor 托管），
# 主连接不在立刻失败、不新握手；其它一律原样交给 /usr/bin/ssh。安全阀：NS_SSH_SHIM=off；监管进程心跳 > 90 s 也原样直连。
REAL=/usr/bin/ssh
STATUS="/d/NS-Final Studio/data/netfix/net_status.json"
[ "${NS_SSH_SHIM:-}" = "off" ] && exec "$REAL" "$@"
if [ -f "$STATUS" ]; then age=$(( $(date +%s) - $(stat -c %Y "$STATUS") )); else age=9999; fi
[ "$age" -gt 90 ] && exec "$REAL" "$@"
kept=(); host=""; args=("$@"); i=0; n=${#args[@]}
while [ $i -lt $n ]; do
  a="${args[$i]}"
  case "$a" in
    --) i=$((i+1)); break ;;
    -[LRDWNMfSO]*) exec "$REAL" "$@" ;;
    -o) v="${args[$((i+1))]}"; k=$(echo "${v%%=*}" | tr 'A-Z' 'a-z')
        case "$k" in controlmaster|controlpath|controlpersist|proxyjump|proxycommand|identityfile|identitiesonly|userknownhostsfile|stricthostkeychecking|hostkeyalias) ;; *) kept+=("-o" "$v") ;; esac
        i=$((i+2)); continue ;;
    -o*) v="${a#-o}"; k=$(echo "${v%%=*}" | tr 'A-Z' 'a-z')
        case "$k" in controlmaster|controlpath|controlpersist|proxyjump|proxycommand|identityfile|identitiesonly|userknownhostsfile|stricthostkeychecking|hostkeyalias) ;; *) kept+=("-o" "$v") ;; esac
        i=$((i+1)); continue ;;
    -[bcEeFIiJlmpPQwB]) i=$((i+2)); continue ;;
    -*) kept+=("$a"); i=$((i+1)); continue ;;
    *) host="$a"; i=$((i+1)); break ;;
  esac
done
h="${host#root@}"
case "$h" in gpu33|gpu36) ;; *) exec "$REAL" "$@" ;; esac
[ $i -ge $n ] && exec "$REAL" "$@"              # 交互式登录不拦
socks=(); for s in cmd cmd2 cmd3 cmd4; do socks+=("/home/fredw/.ssh/nsnf/$h-$s.sock"); done
sock=${socks[$((RANDOM % 4))]}
export MSYS_NO_PATHCONV=1
exec /c/Windows/System32/wsl.exe -d Ubuntu-24.04 --exec ssh -S "$sock" -o ControlMaster=no -o ProxyCommand=false -o BatchMode=yes "${kept[@]}" "$h" "${args[@]:$i}"
