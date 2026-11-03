# W26 SMOKE-GATE：Phase R 冒烟门（RSI 实施包 §4）。一条命令、无人值守：
#   powershell -File eval\run_smoke.ps1
# 输出控制台表 + eval/results/<YYYYMMDD-HHMM>.json（nsfs.smoke/1）；退出码 = 失败门数。评分表 eval/smoke_rubric.md。
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py -X utf8 (Join-Path $root "eval\smoke.py") run
exit $LASTEXITCODE
