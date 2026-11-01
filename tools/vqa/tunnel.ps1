# VQAGATE 11-01：常驻 ssh 隧道 127.0.0.1:8871 → gpu36 127.0.0.1:8870（看图服务）。图片只走自家隧道（K-REV-V01）。
# 断了自动重连；笔记本本机服务（8870）起来后 client 优先连 8870，这条隧道自然闲置。用 Git 自带 ssh（和 Bash 同一份 ~/.ssh/config、密钥）。
$ssh = "C:\Program Files\Git\usr\bin\ssh.exe"
while ($true) {
  & $ssh -o BatchMode=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -N -L 127.0.0.1:8871:127.0.0.1:8870 gpu36
  Start-Sleep -Seconds 15
}
