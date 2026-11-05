#!/bin/bash
# B1（11-05）gpu33 就地看图实例：bash tools/vqa/start_gpu33_vqa.sh [GPU=3] [PORT=8870]   （在 gpu33 上执行；默认不被任何常驻进程调用，运维手工起）
# 前提（一次性，见 BOTTLENECK B1 运维步骤）：/root/work/fredw/vqa/venv（CUDA torch + transformers>=4.57 + bitsandbytes + accelerate）、
#   /root/work/fredw/vqa/models/Qwen3-VL-8B-Instruct（从 gpu36 拷）、server.py + vqa.json 已在 /root/work/fredw/vqa/。
# 红线：GPU2 拒绝（坏卡）；专用常驻（VQA_DEDICATED=1：不空闲卸载、不让道），所以该卡上的 ComfyUI 必须带 --reserve-vram 9，否则抢显存两边 OOM。
set -u
GPU=${1:-3}; PORT=${2:-8870}
[ "$GPU" = 2 ] && { echo "REFUSE gpu33:2"; exit 2; }
B=/root/work/fredw/vqa
[ -x $B/venv/bin/python ] || { echo "NO_VENV $B/venv"; exit 1; }
[ -f $B/models/Qwen3-VL-8B-Instruct/config.json ] || { echo "NO_MODEL"; exit 1; }
if curl -s -m 3 http://127.0.0.1:$PORT/health >/dev/null; then echo "ALREADY_UP :$PORT"; exit 0; fi
FREE=$(nvidia-smi -i $GPU --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
[ "${FREE:-0}" -ge 9000 ] || { echo "VRAM_TOO_LOW free=${FREE}MiB (<9000)"; exit 3; }
mkdir -p $B/logs
cd $B && env VQA_GPUS=$GPU VQA_FORCE_GPU=$GPU VQA_DEDICATED=1 VQA_PORT=$PORT VQA_COMFY= HF_HOME=$B/hf PYTHONUNBUFFERED=1 \
  VQA_HB=/root/work/fredw/gpu_heartbeats/VQA-gpu33-$PORT.json setsid nohup $B/venv/bin/python -u $B/server.py </dev/null >>$B/logs/server_$PORT.log 2>&1 &
echo $! > $B/server_$PORT.pid
sleep 60; curl -s -m 5 http://127.0.0.1:$PORT/health; echo
