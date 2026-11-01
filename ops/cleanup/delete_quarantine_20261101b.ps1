# 永久删除第二次隔离区（项目方本人运行；AI 不运行本脚本）
# 生成：CLEANUP 2026-11-01（总调度 fredw-2b 派）。依据：项目方 11-01 18:3x “把旧的东西全部移出”；旧决定 L-079 “先隔离，验证后你删”。
# 清单：data\_quarantine_20261101b\MANIFEST.md（每项写了原因、引用检查结果和恢复方法）
#
# 用法（PowerShell 7）：
#   先预览（不删任何东西）：  & "D:\NS-Final Studio\ops\cleanup\delete_quarantine_20261101b.ps1"
#   确认删除：                & "D:\NS-Final Studio\ops\cleanup\delete_quarantine_20261101b.ps1" -Delete
#
# 只删除下面 $Targets 里列出的路径，别的一律不碰。隔离区里的 *_orig 目录是本次改过的文档 / 配置 / 规则的原件备份，一并删除。
# 第一次隔离区（data\_quarantine_20261101）另有自己的脚本 delete_quarantine_20261101.ps1。

param([switch]$Delete)

$Root = "D:\NS-Final Studio"
$Targets = @(
    "$Root\data\_quarantine_20261101b"
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
Write-Host "清单：$Root\data\_quarantine_20261101b\MANIFEST.md"

if (-not $Delete) {
    Write-Host "`n预览模式：什么都没删。确认无误后加 -Delete 再运行一次。" -ForegroundColor Green
    return
}

foreach ($t in $Targets) {
    if (Test-Path -LiteralPath $t) {
        Remove-Item -LiteralPath $t -Recurse -Force -Confirm:$false
        Write-Host "已删除 $t" -ForegroundColor Red
    }
}
Write-Host "完成。" -ForegroundColor Green
