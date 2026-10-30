# ep02 端到端测试：项目方本人的关口（S1 验收、造型确认、这次跳过底图）。由项目方本人运行，Claude 会话不代为执行。
# 原话来自项目方（经总调度 fredw-b3 转达）：S1 “验收通过，校验过就渲”；造型 / 底图 “造型确认，这次跳过底图”。
# 封板修复：每步 python 后检查 $LASTEXITCODE，失败即停（原先校验失败也会继续执行验收）。
Set-Location "D:\NS-Final Studio"
$env:PYTHONIOENCODING = "utf-8"
$py = ".venv\Scripts\python.exe"

# 1) S1：剧本校验 0 + 项目方验收（绑定当前 script_v2.json）
& $py tools\s1_gate.py --validator-errors 0
if ($LASTEXITCODE -ne 0) { throw "s1_gate --validator-errors 失败（exit $LASTEXITCODE），已停止，未验收" }
& $py tools\s1_gate.py --accept "验收通过，校验过就渲（项目方 2026-10-30 对 ep02）"
if ($LASTEXITCODE -ne 0) { throw "s1_gate --accept 失败（exit $LASTEXITCODE），已停止" }

# 2) ep02 造型确认（本集出场：林晚、顾沉、陈宇）
foreach ($c in "lin_wan", "gu_chen", "chen_yu") {
  & $py -m ns_agent.looks confirm 2 $c "造型确认，这次跳过底图"
  if ($LASTEXITCODE -ne 0) { throw "looks confirm $c 失败（exit $LASTEXITCODE），已停止" }
}

# 3) 只对 ep02 这一次跳过场景底图要求（其他集照旧；可撤销：--revoke）
& $py tools\s2_waiver.py --episode 2 --skip plate --quote "造型确认，这次跳过底图" --scope "ep02 本次端到端测试渲染"
if ($LASTEXITCODE -ne 0) { throw "s2_waiver 失败（exit $LASTEXITCODE），已停止" }

Write-Host "完成。告诉总调度 / fredw-92：ep02 关口已执行。"
