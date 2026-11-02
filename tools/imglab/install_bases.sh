#!/bin/bash
# IMGLAB 可选基座权重安装（项目方 11-02 11:2x 授权下载免费模型，总调度转）。只下权重，不装节点（两台 ComfyUI 已原生支持 Flux3 / MOSS-Image）。
# 用法: install_bases.sh <comfy_root> <workdir> moss|klein      （klein 需 HF token：环境变量 HF_TOKEN，许可由项目方在 HF 上点同意）
set -u
ROOT=$1; W=$2; WHICH=$3
LOG=$W/install_bases.log
PX="http://10.0.0.101:7190"
mkdir -p "$W"; echo "BEGIN $(date -Is) $WHICH" >> $LOG
dl() {  # url dest sha(可为空=只记录)
  local url=$1 dest=$2 sha=$3; mkdir -p "$(dirname "$dest")"
  if [ -n "$sha" ] && [ -f "$dest" ] && [ "$(sha256sum "$dest" | cut -d' ' -f1)" = "$sha" ]; then echo "HAVE $dest" >> $LOG; return; fi
  local auth=(); local tk="${HF_TOKEN:-}"; [ -z "$tk" ] && [ -f ~/.cache/huggingface/token ] && tk=$(cat ~/.cache/huggingface/token); [ -n "$tk" ] && auth=(-H "Authorization: Bearer $tk")
  https_proxy=$PX curl -sSL --retry 3 "${auth[@]}" -o "$dest.part" "$url" && mv "$dest.part" "$dest"
  got=$(sha256sum "$dest" | cut -d' ' -f1)
  if [ -z "$sha" ] || [ "$got" = "$sha" ]; then echo "OK sha $dest $got" >> $LOG; else echo "FAIL sha $dest got=$got want=$sha" >> $LOG; rm -f "$dest"; fi
}
HF=https://huggingface.co
if [ "$WHICH" = moss ]; then
  R=$HF/Comfy-Org/MOSS-Image/resolve/530a4c94f92c35ef6818b1b035a983fe9dcf5f54
  dl $R/diffusion_models/moss_image_sft_int8_convrot.safetensors "$ROOT/models/diffusion_models/moss_image_sft_int8_convrot.safetensors" b4d1475bc7eeffd7b809e82ea13a1fba1fb85c4e18365af3813722faa5c0fe4f
  dl $R/text_encoders/qwen3.5_9b_int8_convrot.safetensors "$ROOT/models/text_encoders/qwen3.5_9b_int8_convrot.safetensors" 32e3787472f708fa5f83624acbf5ef23f7fc89c439e05065ea57cfe5a97f025a
  dl $R/vae/flux2-vae_small.safetensors "$ROOT/models/vae/flux2-vae_small.safetensors" d8d52ba036475f5fb07c8b435e176d3d97ebfa82f0d1a1c317f9cc1e25bd013b
  dl $R/loras/moss_image_edit_lora_rank_64_bf16.safetensors "$ROOT/models/loras/moss_image_edit_lora_rank_64_bf16.safetensors" 17a48b8c605dcffdedb92a2b887d18cf316505be90802717669fb6556098dcdf
fi
if [ "$WHICH" = klein ]; then
  R=$HF/black-forest-labs/flux-3-image-klein-comfy/resolve/feef60b0aaf63a4773ace96636ebbcf43b881312
  for f in diffusion_models/flux3-image-klein-int8-convrot.safetensors text_encoders/qwen3vl_4b_int8_convrot.safetensors \
           text_encoders/qwen3.5_9b_flux3_prompt_upsampler_int8_convrot.safetensors vae/flux2-vae.safetensors; do
    dl $R/$f "$ROOT/models/$f" ""
  done
  for f in flux3_klein_int8_t2i flux3_klein_int8_i2i flux3_klein_int8_mi2i; do dl $R/workflows/$f.json "$W/workflows/$f.json" ""; done
fi
echo "ALLDONE $(date -Is) $WHICH" >> $LOG
