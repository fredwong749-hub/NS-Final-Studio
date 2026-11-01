# VQAGATE 11-01：网络恢复后的长任务，独立进程跑（不随会话结束）：80 镜首帧回扫（断点续扫，跳板抖就隔 5 分钟再续，最多约 6 小时）
# → V6 数手标定 → eye_contact 标定 → 写拦截预览名单。apply（撤当前 → 自动重出）和打开 video_requires_q9 不在这里：
# 等总调度看过名单再做（AUDIT 建议，不全自动放量）。日志 UTF-8：data/vqa/gate_scan_run3.log
$env:PYTHONUTF8 = "1"
Set-Location "D:\NS-Final Studio"
$py = "D:\NS-Final Studio\.venv\Scripts\python.exe"
$log = "data/vqa/gate_scan_run3.log"
for ($i = 1; $i -le 70; $i++) {
  & $py tools/vqa/gate_scan.py scan --resume 2>&1 | Out-File -Append -Encoding utf8 $log
  $err = & $py -c "import json;r=json.load(open('data/vqa/gate_scan/latest.json',encoding='utf-8'))['rows'];print(sum(1 for x in r if x.get('error')))"
  "$(Get-Date -Format s) 第 $i 遍后看图没跑成 $err 镜" | Out-File -Append -Encoding utf8 $log
  if ($err -eq "0") { break }
  Start-Sleep -Seconds 300
}
& $py tools/vqa/gate_scan.py preview 2>&1 | Out-File -Append -Encoding utf8 $log
& $py tools/vqa/v6_calib.py 2>&1 | Out-File -Encoding utf8 data/vqa/gate_calib/v6_run.log
& $py tools/vqa/gate_scan.py calib_gaze 2>&1 | Out-File -Encoding utf8 data/vqa/gate_calib/gaze_run.log
"done $(Get-Date -Format s)" | Out-File -Encoding utf8 data/vqa/gate_scan/run_after_network.done
