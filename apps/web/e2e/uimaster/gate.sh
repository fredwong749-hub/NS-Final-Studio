#!/usr/bin/env bash
# UIMASTER 改前端后的闸门：tsc + vite build（输出到临时目录，不碰 dist）+ 页面健康抽查。任何一步失败就退出非 0。
set -e
cd "$(dirname "$0")/../.."
npx tsc --noEmit
node e2e/uimaster/selftest.mjs > /dev/null || { echo "爬虫自检失败（node e2e/uimaster/selftest.mjs）"; exit 1; }
# PW-019：组件文件不许新增非组件导出（热更新会退化成整页重载 / 闪屏）；只许减少，基线 e2e/uimaster/refresh_baseline.json
node e2e/uimaster/refresh_check.mjs --gate || exit 1
npx vite build --outDir "${TEMP:-/tmp}/uim_build" --emptyOutDir --logLevel error
# dev server 上不能有 vite 报错层：取首页模块图里任何编译错误
# 开发服务器端口：先试 :5173（稳定通道上线前它就是开发服务器；上线后 :5173 没有 /src/main.tsx，会落到 :5174）；用 UIM_DEV 覆盖。注意 :5174 目前被 VOICE10 的临时 vite 占着（后端 :8812）
DEV="${UIM_DEV:-}"
if [ -z "$DEV" ]; then for p in 5173 5174; do c=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$p/src/main.tsx"); [ "$c" = "200" ] && { DEV="http://127.0.0.1:$p"; break; }; done; fi
[ -n "$DEV" ] || { echo "找不到 vite 开发服务器（:5174 / :5173 的 /src/main.tsx 都不是 200）"; exit 1; }
code=$(curl -s -o /dev/null -w "%{http_code}" "$DEV/src/main.tsx")
[ "$code" = "200" ] || { echo "vite dev 模块 main.tsx 返回 $code"; exit 1; }
# DATAALIGN（K-UI-D01）：界面字段 = 后端源数据（tools/qa/data_parity.py，docs/DATA_MAP.md）。1 = 不一致 → 闸门失败；2 = 未测（:8800 未起 / 旧代码待重启）→ 只警告
PY="../../.venv/Scripts/python.exe"; [ -x "$PY" ] || PY=python
set +e
"$PY" ../../tools/qa/data_parity.py | tail -n 12
pc=${PIPESTATUS[0]}
set -e
[ "$pc" = "1" ] && { echo "DATA PARITY FAIL（见上；契约 docs/DATA_MAP.md）"; exit 1; }
[ "$pc" = "2" ] && echo "DATA PARITY 未测（警告，不算通过）"
echo "GATE OK"
