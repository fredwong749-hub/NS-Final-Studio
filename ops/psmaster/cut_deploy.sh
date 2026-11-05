#!/bin/bash
# 通用发版：cut_deploy.sh <LIST 文件> [标签]   —— LIST 文件 → 拼树 → cut（id 用 next_id，不写死）→ deploy 两台 → verify。失败即停。
# REVIEW-C：id 由 system_version.next_id() 在 cut 时取（cut 自带全局互斥；并发撞车 rc 3）。旧的 cut_deploy_*.sh 保持不动。
LIST="$1"; TAG="${2:-run}"
[ -n "$LIST" ] && [ -f "$LIST" ] || { echo "用法：$0 <LIST 文件> [标签]"; exit 1; }
cd "/d/NS-Final Studio" || exit 1
export TZ=JST-9 PYTHONIOENCODING=utf-8 PYTHONUTF8=1 NS_CUT_PYTEST_N=4
PY=.venv/Scripts/python.exe; LOG=data/system_versions/cut_${TAG}_run.log
exec > >(tee -a "$LOG") 2>&1
echo "== $(date) start (list=$LIST)"
TREE=$($PY -c "import sys;sys.path.insert(0,'tools/qa');import system_version as s;from pathlib import Path;print(s.build_tree_from_list(Path(sys.argv[1]))['tree'])" "$LIST") || { echo "FAIL build tree"; exit 1; }; echo tree=$TREE
ID=$($PY -c "import sys;sys.path.insert(0,'tools/qa');import system_version as s;print(s.next_id())") || { echo "FAIL next_id"; exit 1; }; echo id=$ID
$PY tools/qa/system_version.py cut --on local --id $ID --tree $TREE --report-json data/system_versions/${ID}_cut.json; rc=$?
[ $rc -eq 0 ] || { echo "FAIL cut rc=$rc（3 = 别的 cut 在跑 / id 已存在，别重试撞车）"; exit 2; }
$PY tools/qa/system_version.py deploy $ID --verify-shot 8 --verify-run series10_v2 --report-json data/system_versions/deploy_${ID}_report.json || { echo "FAIL deploy/verify"; exit 3; }
echo "== $(date) ALL OK $ID"
