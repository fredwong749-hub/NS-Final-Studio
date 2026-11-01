#!/bin/bash
# VQA 离线部署（在服务器上执行）：bash deploy_offline.sh gpu33|gpu36 <vqa_code.tgz>
# 只新增自己的进程：本地看图服务（/root/work/fredw/vqa/server.pid）+ watcher（offline_20261101/run/vqa.pid，日志 logs/vqa.out）。
# 不动 producer / night / fwd；gpu33 用 CPU（出图卡常年满、GPU3 是视频道、GPU2 永不用）；gpu36 用 GPU0/1 让道模式，不碰功耗墙。
set -u
SELF=$1; TGZ=$2
OFF=/root/work/fredw/offline_20261101; B=/root/work/fredw/vqa
mkdir -p $B/logs $B/models $OFF/logs $OFF/run
tar -xzf "$TGZ" -C $OFF/repo || { echo UNPACK_FAIL; exit 1; }
cp $OFF/repo/tools/vqa/server.py $OFF/repo/config/vqa.json $B/
PX="export https_proxy=http://10.0.0.101:7190 http_proxy=http://10.0.0.101:7190 no_proxy=localhost,127.0.0.1,10.0.0.0/8"

if [ ! -x $B/venv/bin/python ]; then      # gpu33 首次：自己的 venv + 模型（代理只给这几条命令）
  UV=$(ls /root/work/fredw/uvtool/bin/uv /root/claude-kimi-ns-studio-v1/env/uv/uv /root/.local/bin/uv 2>/dev/null | head -1)
  PY=$(ls -d /root/claude-kimi-ns-studio-v1/env/python/cpython-3.12*/bin/python3.12 /root/work/fredw/python/cpython-3.12*/bin/python3.12 2>/dev/null | head -1)
  echo "uv=$UV py=$PY"
  ( eval "$PX"; export UV_CACHE_DIR=$B/uvcache
    $UV venv -p "$PY" $B/venv && $UV pip install -p $B/venv/bin/python --index-strategy unsafe-best-match \
      --extra-index-url https://download.pytorch.org/whl/cpu "torch==2.11.0" torchvision "transformers>=4.57" accelerate \
      pillow opencv-python-headless numpy "huggingface_hub[cli]" hf_xet ) > $B/logs/setup.log 2>&1 || { echo VENV_FAIL; tail -5 $B/logs/setup.log; exit 1; }
fi
if [ ! -f $B/models/Qwen3-VL-8B-Instruct/config.json ] || [ "$(ls $B/models/Qwen3-VL-8B-Instruct/*.safetensors 2>/dev/null | wc -l)" -lt 4 ]; then
  ( eval "$PX"; export HF_HOME=$B/hf; $B/venv/bin/hf download Qwen/Qwen3-VL-8B-Instruct --local-dir $B/models/Qwen3-VL-8B-Instruct ) >> $B/logs/setup.log 2>&1 \
    || { echo MODEL_FAIL; tail -5 $B/logs/setup.log; exit 1; }
fi

# 本地看图服务（重启自己的）
[ -f $B/server.pid ] && kill "$(cat $B/server.pid)" 2>/dev/null; sleep 2
if [ "$SELF" = gpu33 ]; then ENV="VQA_DEVICE=cpu VQA_THREADS=24"; else ENV="VQA_GPUS=0,1 VQA_COMFY=0:8188,1:8189"; fi
cd $B && env $ENV HF_HOME=$B/hf PYTHONUNBUFFERED=1 setsid nohup $B/venv/bin/python -u $B/server.py </dev/null >>$B/logs/server.log 2>&1 &
echo $! > $B/server.pid

# watcher
P=$OFF/run/vqa.pid
[ -f $P ] && kill "$(cat $P)" 2>/dev/null; sleep 1
cd $OFF/repo && OFFLINE_SELF=$SELF PYTHONUTF8=1 PYTHONIOENCODING=utf-8 setsid nohup $B/venv/bin/python -u tools/vqa/watch.py </dev/null >>$OFF/logs/vqa.out 2>&1 &
echo $! > $P

grep -q "VQA 看图复核" $OFF/TASKS.md || cat >> $OFF/TASKS.md <<EOF

## VQA 看图复核（11-01 追加，总调度派，只记录）
- 进程：watcher（run/vqa.pid，logs/vqa.out）+ 本地看图服务 Qwen3-VL-8B（/root/work/fredw/vqa/server.pid，127.0.0.1:8870，日志 /root/work/fredw/vqa/logs/server.log）。$( [ "$SELF" = gpu33 ] && echo "gpu33 只用 CPU（24 线程），不占 GPU" || echo "gpu36 只用 GPU0/1，ComfyUI 队列空 + 显存余量 ≥7 GB 才加载，来活即卸载，不碰功耗墙" )。
- 做什么：冻结之后新出的首帧 / 尾帧逐张在本机看图（图片不出服务器、不调外部 API）→ repo/data/vqa/（verdicts、index.json 供 postflight Q9、records.jsonl 含规则裁判的修改建议）。不改 takes.json、不重派。
- 停：kill \$(cat run/vqa.pid)；resume_from_gpu33.sh 会一并停。
EOF
sleep 5
echo "server $(cat $B/server.pid) $(kill -0 $(cat $B/server.pid) 2>/dev/null && echo alive || echo DEAD); watcher $(cat $P) $(kill -0 $(cat $P) 2>/dev/null && echo alive || echo DEAD)"
tail -3 $OFF/logs/vqa.out
