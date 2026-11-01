#!/bin/bash
S=$HOME/.ssh/nsnf/test36.sock
ssh -o BatchMode=yes -M -S "$S" -o ControlPersist=300 -fN -L 127.0.0.1:28888:127.0.0.1:8188 gpu36
ss -ltn | grep 28888
curl -s -m 20 -w " http=%{http_code}" http://127.0.0.1:28888/system_stats | tail -c 40; echo
