#!/bin/bash
# CODER-AUTO 11-05：cut P（L-196 全自动闸门，按交付清单）→ deploy 两台 → verify。失败即停。日志 data/system_versions/cutP_run.log
cd "/d/NS-Final Studio" || exit 1
export TZ=JST-9 PYTHONIOENCODING=utf-8 PYTHONUTF8=1 NS_CUT_PYTEST_N=4
PY=.venv/Scripts/python.exe; LOG=data/system_versions/cutP_run.log; ID=sv-20261105-10
M="CODER-AUTO-20261105"
exec > >(tee -a "$LOG") 2>&1
echo "== $(date) start $ID manifests: $M"
$PY tools/qa/system_version.py cut --on local --id $ID --manifests $M --report-json data/system_versions/${ID}_cut.json || { echo "FAIL cut（闸门不过，未提交、未部署）"; exit 2; }
echo "== $(date) cut ok"
$PY tools/qa/system_version.py deploy $ID --verify-shot 8 --verify-run series10_v2 --report-json data/system_versions/deploy_${ID}_report.json || { echo "FAIL deploy/verify"; exit 3; }
echo "== $(date) ALL OK $ID"
