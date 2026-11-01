#!/usr/bin/env bash
# 前端改动写回（UIMASTER 起，UIRSI 11-01 改：先沙盒、后真文件）：
#   1) 算出新内容（整份替换，或 --replace 把 old 段换成 new 段）
#   2) 把 apps/web/src 复制到沙盒 apps/web/.tsc_sandbox/src，新内容只写进沙盒，在沙盒里跑 tsc（模块解析会往上找到 apps/web/node_modules）
#   3) 沙盒 tsc 通过 → 再用 safe_write（语法检查 + 原子替换）写真文件；不通过 → 真文件一个字节都不动
# 这样导入方永远不会在中途拿不到导出（以前是先写真文件再跑 tsc、不过再回滚，中间约 10 秒是坏的）。
# 用法：bash safe_edit.sh <目标文件> <新内容文件>
#       bash safe_edit.sh <目标文件> --replace <old 文件> <new 文件>
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
WEB="$ROOT/apps/web"
PY="$ROOT/.venv/Scripts/python.exe"
T="$1"; shift
TABS="$(cd "$(dirname "$T")" && pwd)/$(basename "$T")"
case "$TABS" in "$WEB/src/"*) ;; *) echo "只管 apps/web/src 下的文件：$T"; exit 2;; esac
REL="${TABS#"$WEB/"}"

# 1) 新内容
NEW="$(mktemp)"
if [ "${1:-}" = "--replace" ]; then
  "$PY" - "$TABS" "$2" "$3" "$NEW" <<'PY' || { rm -f "$NEW"; exit 2; }
import sys
from pathlib import Path
cur = Path(sys.argv[1]).read_text(encoding="utf-8")
old = Path(sys.argv[2]).read_text(encoding="utf-8")
new = Path(sys.argv[3]).read_text(encoding="utf-8")
if cur.count(old) != 1:
    print(f"old 段在目标文件里出现 {cur.count(old)} 次（要恰好 1 次）"); sys.exit(2)
Path(sys.argv[4]).write_text(cur.replace(old, new), encoding="utf-8")
PY
else
  cp "$1" "$NEW"
fi

# 2) 沙盒 tsc（真文件不动）
# 沙盒放在 node_modules/.cache 下：vite 不监视 node_modules。以前放在 apps/web/.tsc_sandbox，每次建删 tsconfig.json
# 都会被 vite 当成配置变化 → 项目方的 :5173 整页重载（PW-020：08:26–08:35 重载 56 次）
SB="$WEB/node_modules/.cache/uim_tsc_sandbox_$$"  # 每次运行一个独立沙盒：几个 agent 同时跑时互不删对方的（UIPIXEL 11-01 碰到 TS5058）
rm -rf "$SB"; mkdir -p "$SB"
cp -r "$WEB/src" "$SB/src"
cp "$WEB/tsconfig.json" "$SB/tsconfig.json"
cp "$WEB/vite.config.ts" "$SB/vite.config.ts" 2>/dev/null || true
cp "$NEW" "$SB/$REL"
if ! (cd "$SB" && "$WEB/node_modules/.bin/tsc" -p tsconfig.json --noEmit > "$SB/tsc.txt" 2>&1); then
  echo "沙盒 tsc 不过，真文件没动：$T"; head -8 "$SB/tsc.txt"; rm -f "$NEW"; rm -rf "$SB"; exit 1
fi

# 3) 写真文件（语法检查 + 原子替换）
"$PY" "$WEB/e2e/uirsi/safe_write.py" "$TABS" "$NEW" || { rm -f "$NEW"; rm -rf "$SB"; exit 1; }
rm -f "$NEW"; rm -rf "$SB"; echo "OK $T"
