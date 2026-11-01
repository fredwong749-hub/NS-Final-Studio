# 永久删除隔离区与已归档旧剧目录（项目方本人运行；AI 不运行本脚本）
# 生成：RECALL 2026-11-01。依据：项目方一键决定“先隔离，验证后你删”。清单：data\_quarantine_20261101\MANIFEST.md
#
# 用法（PowerShell 7）：
#   先预览（不删任何东西）：  & "D:\NS-Final Studio\ops\cleanup\delete_quarantine_20261101.ps1"
#   确认删除：                & "D:\NS-Final Studio\ops\cleanup\delete_quarantine_20261101.ps1" -Delete
#
# 只删除下面 $Targets 里列出的路径，别的一律不碰。

param([switch]$Delete)

$Root = "D:\NS-Final Studio"
$Targets = @(
    "$Root\data\_quarantine_20261101",
    "$Root\_quarantine_code_20261101",
    "$Root\data\renders\_archive_60ep_20261031",
    "$Root\data\renders_gpu3\_archive_60ep_20261031",
    "$Root\data\_archive\20261031",
    "$Root\data\_archive\20261031_r2",
    "$Root\data\import\backups\script_v2.20261030-220659.json",
    "$Root\data\import\backups\script_v2.20261031-172058.json",
    "$Root\data\import\backups\script_v2.20261031-200848.json",
    "$Root\data\import\backups\script_v2.20261031-231559.json"
)

function Get-SizeBytes([string]$p) {
    $it = Get-Item -LiteralPath $p -Force
    if ($it.PSIsContainer) {
        return (Get-ChildItem -LiteralPath $p -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    }
    return $it.Length
}

$total = 0
Write-Host "==== 将要删除的路径 ====" -ForegroundColor Cyan
foreach ($t in $Targets) {
    if (Test-Path -LiteralPath $t) {
        $b = [int64](Get-SizeBytes $t)
        $total += $b
        "{0,10:N1} MB  {1}" -f ($b / 1MB), $t | Write-Host
    } else {
        "   (不存在)    $t" | Write-Host -ForegroundColor DarkGray
    }
}
"合计 {0:N2} GB" -f ($total / 1GB) | Write-Host -ForegroundColor Yellow

if (-not $Delete) {
    Write-Host "`n预览模式：什么都没删。确认无误后加 -Delete 再运行一次。" -ForegroundColor Green
    Write-Host "服务器上的隔离区见脚本末尾的 bash 段（需要在 gpu33 / gpu36 各运行一次）。"
    return
}

foreach ($t in $Targets) {
    if (Test-Path -LiteralPath $t) {
        Remove-Item -LiteralPath $t -Recurse -Force -Confirm:$false
        Write-Host "已删除 $t" -ForegroundColor Red
    }
}
Write-Host "笔记本部分完成。" -ForegroundColor Green

<#
==== 服务器隔离区（bash；分别在 gpu33 和 gpu36 上执行，或从笔记本 ssh 执行）====
只删 /root/work/fredw/_quarantine_20261101，别的不碰。先看再删：

ssh -o BatchMode=yes gpu33 'du -sh /root/work/fredw/_quarantine_20261101/loras/*/* 2>/dev/null; du -sh /root/work/fredw/_quarantine_20261101'
ssh -o BatchMode=yes gpu36 'du -sh /root/work/fredw/_quarantine_20261101/loras/*/* 2>/dev/null; du -sh /root/work/fredw/_quarantine_20261101'

确认后删除：
ssh -o BatchMode=yes gpu33 'Q=/root/work/fredw/_quarantine_20261101; [ -d "$Q" ] && rm -rf -- "$Q" && echo deleted $Q'
ssh -o BatchMode=yes gpu36 'Q=/root/work/fredw/_quarantine_20261101; [ -d "$Q" ] && rm -rf -- "$Q" && echo deleted $Q'
#>
