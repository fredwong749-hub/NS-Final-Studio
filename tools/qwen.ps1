# 在 PowerShell 里打开 gpu3 Docker 容器里的 Qwen Code 交互界面（类似 claude 命令）。
#   powershell -ExecutionPolicy Bypass -File "D:\NS-Final Studio\tools\qwen.ps1"          # Qwen Code（容器 qwen-agent，工作区 /work）
#   powershell -ExecutionPolicy Bypass -File "D:\NS-Final Studio\tools\qwen.ps1" -Chat    # 只和写作模型对话（tools/qwen_chat.py）
# 规则见 docs/qwen_comms.md；退出 Qwen Code 用 /quit 或 Ctrl+C 两次。
param([switch]$Chat)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if ($Chat) {
    Set-Location "D:\NS-Final Studio"
    uv run python tools/qwen_chat.py
} else {
    ssh -t -o ServerAliveInterval=15 gpu33 "docker exec -it -w /work qwen-agent qwen --auth-type openai"
}
