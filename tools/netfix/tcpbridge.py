"""stdio ↔ TCP 桥（NETFIX r2）：WSL 里的 ssh 用 ProxyCommand 调 Windows 侧本程序，连到 Windows 127.0.0.1:22360 / 22330（底座隧道端口）。
WSL2 NAT 模式下 WSL 访问不到 Windows 的 127.0.0.1，又不许把隧道口绑到 0.0.0.0，所以走 WSL interop 的标准输入输出。
  python tcpbridge.py 127.0.0.1 22360"""
import os
import socket
import sys
import threading

if os.name == "nt":
    import msvcrt
    msvcrt.setmode(0, os.O_BINARY)
    msvcrt.setmode(1, os.O_BINARY)


def main():
    s = socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=15)
    s.settimeout(None)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def up():
        try:
            while True:
                d = os.read(0, 65536)
                if not d:
                    break
                s.sendall(d)
        except OSError:
            pass
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    threading.Thread(target=up, daemon=True).start()
    try:
        while True:
            d = s.recv(65536)
            if not d:
                break
            os.write(1, d)
    except OSError:
        pass


if __name__ == "__main__":
    main()
