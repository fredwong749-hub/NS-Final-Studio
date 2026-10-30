#!/bin/bash
# LoRA 训练实时状态：每 60 秒刷新一次（在你自己的终端里运行，不消耗 Claude token）
# 用法（Git Bash）：bash "/d/NS-Final Studio/tools/lora_status.sh"     退出：Ctrl+C
while true; do
  out=$(timeout 50 ssh -n -o BatchMode=yes -o ConnectTimeout=15 gpu33 '
B=/root/claude-kimi-ns-studio-v1/ns-studio/data/train; W=$B/wardrobe; J=$B/jewellery
echo "gpu3 时间: $(date "+%F %T")"
echo "---- 显卡 ----"
nvidia-smi --query-gpu=index,utilization.gpu,memory.used,temperature.gpu --format=csv,noheader | sed "s/^/GPU /"
echo "---- 占用 ----"
for f in /root/.local/state/NS-Studio/gpu.lock.gpu* /root/.local/state/NS-Studio/train.lock.gpu*; do [ -e "$f" ] && echo "$(basename $f): $(head -c 90 $f)"; done
echo "---- 乳环/阴环 ----"
echo "nprng2 写实图: $(ls $J/render/nprng2_01*/final_v1.png 2>/dev/null | wc -l)/100"
tail -1 $J/logs/pipeline.log 2>/dev/null | cut -c1-110
for t in $J/logs/train_*.log; do [ -e "$t" ] && echo "$(basename $t): $(grep -oE "[0-9]+/[0-9]+ \[[^]]*\]" $t | tail -1) loss $(grep -oE "loss[:=] ?[0-9.]+" $t | tail -1)"; done
echo "---- 鞋/衣服 ----"
for d in hh12clear hh12patent persons clothes; do [ -d $W/synth/$d ] && echo "$d: $(ls $W/synth/$d/*.png 2>/dev/null | wc -l) 张"; done
grep -h REVIEW_SHEET $W/logs/pipe_heels.log $W/logs/pipe_clothes.log 2>/dev/null | tail -2
ls $W/REVIEWED_* 2>/dev/null
echo "---- 林晚/姿势 ----"
echo "GPU0 借用: $(head -c 80 /root/.local/state/NS-Studio/lend.gpu0 2>/dev/null)"
ls /root/claude-kimi-ns-studio-v1/tools/weita_v3/work/FINISH_* 2>/dev/null | sed "s#.*/#v3: #"
echo "---- 已登记 LoRA ----"
python3 -c "import json;d=json.load(open(\"/root/claude-kimi-ns-studio-v1/nsfs_mirror/data/renders_gpu3/LORA_REGISTRY.json\"));print(\"\n\".join(f\"{x.get(\x27lora_id\x27)}: {x.get(\x27status\x27)}\" for x in d.get(\"loras\",[])) or \"（无）\")"
' 2>/dev/null)
  clear
  echo "=== LoRA 训练实时状态（每 60 秒刷新，Ctrl+C 退出）==="
  echo "${out:-gpu3 连接失败，60 秒后重试}"
  sleep 60
done
