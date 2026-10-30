#!/bin/bash
# fredw-92 2026-10-30，项目方指示：“林晚lora训完马上接视频lora”。一次性接力（在 gpu3 上跑，跑完即退出）：
# lw-qi-lora（林晚出图 LoRA，GPU0）交付后，把 lw-lora-pipeline（林晚视频 LoRA lnwan01）从 GPU1（项目方：GPU1 归 Qwen）
# 移到 GPU0：已保留的训练图跳过，剩余补图与训练都在 GPU0 续跑。
# 用法（笔记本上由项目方执行）：
#   ssh gpu33 'cat > /root/claude-kimi-ns-studio-v1/tools/lw_lora/gpu0_relay.sh && chmod +x $_' < "D:/NS-Final Studio/ops/gpu0_relay.sh"
#   ssh gpu33 systemd-run --unit=lw-gpu0-relay -p StandardOutput=append:/root/claude-kimi-ns-studio-v1/logs/lw_lora/gpu0_relay.log /root/claude-kimi-ns-studio-v1/tools/lw_lora/gpu0_relay.sh
ST=/root/.local/state/NS-Studio; B=/root/claude-kimi-ns-studio-v1
QI=$B/ns-studio/data/train/lin_wan_qi; H3=$B/ns-studio/data/train/lin_wan_h3_v2
log() { echo "$(date '+%F %T') $*"; }
until [ -f $QI/.done ]; do sleep 60; done; log "lin_wan_qi delivered (.done)"
until ! pgrep -f lw_qi_pipeline.sh >/dev/null; do sleep 20; done
until [ ! -e $ST/train.lock.gpu0 ]; do sleep 20; done
echo "lw-lora (fredw-92 $(date -Is): owner — Lin Wan video LoRA right after the image LoRA; GPU1 is Qwen's)" > $ST/lend.gpu0
log "lend.gpu0 -> lw-lora"
[ -f $H3/output/lin_wan_h3_v1/lin_wan_h3_v1.safetensors ] && { log "video LoRA already trained"; exit 0; }
systemctl stop lw-lora-pipeline 2>/dev/null; sleep 10
pkill -f "gen_dataset.py --slots gpu1" 2>/dev/null; sleep 5
grep -qs "lw_dataset" $ST/gpu.lock.gpu1 && rm -f $ST/gpu.lock.gpu1
systemd-run --unit=lw-lora-pipeline -E FORCE_GPU=0 -p StandardOutput=append:$B/logs/lw_lora/pipeline.log \
  -p StandardError=append:$B/logs/lw_lora/pipeline.log $B/tools/lw_lora/lw_pipeline.sh
log "lw-lora-pipeline restarted on GPU0 (stills resume, then training)"
