#!/bin/bash
# PS-MASTER 11-05：cut N（按交付清单）→ deploy 两台 → verify。失败即停。日志 data/system_versions/cutN_run.log
cd "/d/NS-Final Studio" || exit 1
export TZ=JST-9 PYTHONIOENCODING=utf-8 PYTHONUTF8=1 NS_CUT_PYTEST_N=4
PY=.venv/Scripts/python.exe; LOG=data/system_versions/cutN_run.log; ID=sv-20261105-08
M="PS-MASTER-N-20261105"
exec > >(tee -a "$LOG") 2>&1
echo "== $(date) start $ID manifests: $M"
TREE=$($PY -c "import sys;sys.path.insert(0,'tools/qa');import system_version as s;from pathlib import Path;print(s.build_tree_from_list(Path('docs/system_versions/LIST_cutN.txt'))['tree'])") || { echo "FAIL build tree"; exit 1; }; echo tree=$TREE
$PY tools/qa/system_version.py cut --on local --id $ID --tree $TREE --report-json data/system_versions/${ID}_cut.json || { echo "FAIL cut（闸门不过，未提交、未部署）"; exit 2; }
echo "== $(date) cut ok"
$PY tools/qa/system_version.py deploy $ID --verify-shot 8 --verify-run series10_v2 --report-json data/system_versions/deploy_${ID}_report.json || { echo "FAIL deploy/verify"; exit 3; }
echo "== $(date) ALL OK $ID"
