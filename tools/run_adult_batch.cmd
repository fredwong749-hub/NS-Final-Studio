@echo off
rem 双击运行：渲染成人镜头首帧（等 GPU 空闲后开始）。要连尾帧一起出：在命令行加 -Stage both（视频在 gpu3 出）
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_adult_batch.ps1" %*
pause
