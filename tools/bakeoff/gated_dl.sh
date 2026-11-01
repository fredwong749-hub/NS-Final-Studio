#!/bin/bash
# BAKEOFF：BFL gated 仓库下载（FLUX.2 klein 9B / FLUX.3 klein）。
# 令牌：项目方自己放在 /root/work/fredw/hf/token（600）。本脚本不 echo、不 set -x、不写日志；
# 令牌只经 curl 的 -H @<(...)（进程替换，不进命令行参数）注入下载/查询那一条命令。
# 等令牌文件出现后开始；每个文件先用 HF API（带令牌）取 LFS oid 和字节数，下载后 sha256 必须等于 oid 才移入 models。
# 用法：nohup bash gated_dl.sh <models根目录> > run/gated.log 2>&1 &
set -u
MODELS=$1
TOK=/root/work/fredw/hf/token
DL=/root/work/fredw/dl; mkdir -p "$DL"; LOG=$DL/sha256.log
PX="https_proxy=http://10.0.0.101:7190 http_proxy=http://10.0.0.101:7190 no_proxy=localhost,127.0.0.1,10.0.0.0/8"
# 仓库 固定版本 仓库内路径 models子目录 本地文件名
LIST="black-forest-labs/FLUX.2-klein-9B 92196c8e11f7b6cf2b7493e037d8c5345c559216 flux-2-klein-9b.safetensors diffusion_models flux-2-klein-9b.safetensors
black-forest-labs/FLUX.2-klein-base-9B 32773329fbe7e81a90ef971740e8ba4b0364ecf3 flux-2-klein-base-9b.safetensors diffusion_models flux-2-klein-base-9b.safetensors
black-forest-labs/flux-3-image-klein-comfy feef60b0aaf63a4773ace96636ebbcf43b881312 diffusion_models/flux3-image-klein-int8-convrot.safetensors diffusion_models flux3-image-klein-int8-convrot.safetensors
black-forest-labs/flux-3-image-klein-comfy feef60b0aaf63a4773ace96636ebbcf43b881312 diffusion_models/flux3-image-klein-base-int8-convrot.safetensors diffusion_models flux3-image-klein-base-int8-convrot.safetensors
black-forest-labs/flux-3-image-klein-comfy feef60b0aaf63a4773ace96636ebbcf43b881312 text_encoders/qwen3vl_4b_int8_convrot.safetensors text_encoders flux3_qwen3vl_4b_int8_convrot.safetensors
black-forest-labs/flux-3-image-klein-comfy feef60b0aaf63a4773ace96636ebbcf43b881312 vae/flux2-vae.safetensors vae flux3_flux2-vae.safetensors
black-forest-labs/flux-3-image-klein-comfy feef60b0aaf63a4773ace96636ebbcf43b881312 workflows/README.md - flux3_workflows_README.md"
while [ ! -s "$TOK" ]; do sleep 60; done
echo "$(date +%T) 令牌文件已出现，开始"
hfcurl() { env $PX curl -sSL --fail -H @<(printf 'Authorization: Bearer %s\n' "$(cat "$TOK")") "$@"; }
echo "$LIST" | while read -r repo rev path sub name; do
  dir=$(dirname "$path"); [ "$dir" = "." ] && dir=""
  meta=$(hfcurl "https://huggingface.co/api/models/$repo/paths-info/$rev" --data-urlencode "paths=$path" 2>/dev/null)
  if [ -z "$meta" ]; then echo "$(date +%T) NO_ACCESS $repo（协议未接受或令牌无权限）"; continue; fi
  size=$(printf '%s' "$meta" | python3 -c 'import sys,json; d=json.load(sys.stdin)[0]; print(d.get("size",0))')
  oid=$(printf '%s' "$meta" | python3 -c 'import sys,json; d=json.load(sys.stdin)[0]; print((d.get("lfs") or {}).get("oid",""))')
  if [ "$sub" = "-" ]; then hfcurl -o "/root/work/fredw/bakeoff/srv/$name" "https://huggingface.co/$repo/resolve/$rev/$path" && echo "$(date +%T) OK $name"; continue; fi
  dest=$MODELS/$sub/$name
  if [ -f "$dest" ] && [ "$(stat -c %s "$dest")" = "$size" ]; then echo "$(date +%T) SKIP $name"; continue; fi
  echo "$(date +%T) GET $name $((size/1000000))MB"
  for try in 1 2 3 4 5; do hfcurl -C - --retry 3 -o "$DL/$name.part" "https://huggingface.co/$repo/resolve/$rev/$path" && break; sleep 10; done
  got=$(stat -c %s "$DL/$name.part" 2>/dev/null || echo 0)
  if [ "$got" != "$size" ]; then echo "$(date +%T) SIZE_BAD $name $got != $size"; echo "$name $got - $repo@$rev SIZE_BAD" >> $LOG; rm -f "$DL/$name.part"; continue; fi
  s=$(sha256sum "$DL/$name.part" | cut -d' ' -f1)
  if [ -n "$oid" ] && [ "$s" = "$oid" ]; then
    mv "$DL/$name.part" "$dest"; touch "$MODELS/$sub"; echo "$name $size $s $repo@$rev OK" >> $LOG; echo "$(date +%T) OK $name"
  else
    echo "$name $size $s $repo@$rev SHA_BAD(want $oid)" >> $LOG; echo "$(date +%T) SHA_BAD $name"
  fi
done
echo "$(date +%T) DONE"
