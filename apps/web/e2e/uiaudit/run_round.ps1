# UIAUDIT 一轮复测：任务 + 功能回退 + 滚动。用法：pwsh run_round.ps1 r4
param([string]$R = "rX", [string]$Web = "")
if ($Web) { $env:NS_WEB = $Web } else { Remove-Item Env:NS_WEB -ErrorAction SilentlyContinue }
Set-Location $PSScriptRoot
$env:DETECT_PORT = ""
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | ? { $_.CommandLine -match 'uiaudit_chrome_' } | % { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
node detect.mjs flows_tasks.json "${R}t" *> "${R}_tasks_stdout.txt"
Start-Sleep 3; node detect.mjs flows_regress.json "${R}g" *> "${R}_regress_stdout.txt"
node regress_check.mjs "${R}g_detect.json" > "${R}_regress.md"
node parity_check.mjs "${R}g_detect.json" > "${R}_parity.md"
# DATAALIGN 的数据一致检查（界面 = 后端），退出码非 0 = P0
& ..\..\..\..\.venv\Scripts\python.exe ..\..\..\..\tools\qa\data_parity.py --all --ui 2 --json "${R}_data_parity.json" *> "${R}_data_parity.txt"; "data_parity exit=$LASTEXITCODE" | Add-Content "${R}_data_parity.txt"
# r22 起：UIRSI 交给 UIAUDIT 的回归流程（r37：候选弹窗真实鼠标、窄格悬停显示、剧本页宽格常显示）+ 本方 r37 复核流程，一并跑
Start-Sleep 3; node detect.mjs flows_r37.json "${R}u" *> "${R}_r37_stdout.txt"; node detect.mjs flows_r37v.json "${R}v" *> "${R}_r37v_stdout.txt"
node regress.mjs HEAD > "${R}_regress_static.json"
Start-Sleep 3; node detect.mjs scroll_all.json "${R}s" *> "${R}_scroll_stdout.txt"
node summarize.mjs "${R}s_detect.json" > "${R}_scroll.md"
"done $R"






Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | ? { $_.CommandLine -match 'uiaudit_chrome_' } | % { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }



