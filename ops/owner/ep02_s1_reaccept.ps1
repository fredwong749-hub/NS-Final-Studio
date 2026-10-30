# ep02：剧本 JSON 补了 globals.daily_outfit / decor_tables（总调度选 A），S1 验收需项目方本人重新执行。由项目方本人运行。
# 造型确认与这次跳过底图按集记录，不受影响，不用重做。
# 封板修复：每步 python 后检查 $LASTEXITCODE，校验失败即停，不再继续验收。
Set-Location "D:\NS-Final Studio"
$env:PYTHONIOENCODING = "utf-8"
$py = ".venv\Scripts\python.exe"

& $py tools\s1_gate.py --validator-errors 0
if ($LASTEXITCODE -ne 0) { throw "s1_gate --validator-errors 失败（exit $LASTEXITCODE），已停止，未验收" }
& $py tools\s1_gate.py --accept "验收通过，校验过就渲"
if ($LASTEXITCODE -ne 0) { throw "s1_gate --accept 失败（exit $LASTEXITCODE），已停止" }

Write-Host "完成。告诉总调度：ep02 S1 已重新验收。"
