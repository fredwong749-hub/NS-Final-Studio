' NS-Final Studio 实时监控看板 (http://127.0.0.1:8810)，静默启动（无黑窗）
' 端口已被占用时（看板已在跑）会自动退出，不会起两份
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\NS-Final Studio"
sh.Run """D:\NS-Final Studio\.venv\Scripts\pythonw.exe"" tools\monitor\server.py", 0, False
