#!/bin/bash
# BAKEOFF 权重下载（gpu36/gpu33 上跑）：按 dl_manifest.tsv 逐个下，代理只写在 curl 这一行；
# 先下到 /root/work/fredw/dl/ 暂存，sha256 == HF LFS oid 才移进 models/<子目录>/ 并 touch 目录让 ComfyUI 重扫。
# 用法：bash dl_weights.sh <manifest.tsv> <models根目录> [阶段 A,B,C]
# 记录：/root/work/fredw/dl/sha256.log（文件名 字节 sha256 来源 结果）
set -u
MAN=$1; MODELS=$2; PHASES=${3:-A,B,C}
DL=/root/work/fredw/dl; mkdir -p "$DL"; LOG=$DL/sha256.log
PROXY="https_proxy=http://10.0.0.101:7190 http_proxy=http://10.0.0.101:7190 no_proxy=localhost,127.0.0.1,10.0.0.0/8"
grep -v '^#' "$MAN" | while IFS=$'\t' read -r ph repo rev path sub size sha; do
  [ -z "$ph" ] && continue
  case ",$PHASES," in *",$ph,"*) ;; *) continue;; esac
  name=$(basename "$path"); dest=$MODELS/$sub/$name
  if [ -f "$dest" ] && [ "$(stat -c %s "$dest")" = "$size" ]; then echo "$(date +%T) SKIP $name (已在)"; continue; fi
  url="https://huggingface.co/$repo/resolve/$rev/$path"
  echo "$(date +%T) GET $name $((size/1000000))MB"
  for try in 1 2 3 4 5; do
    env $PROXY curl -sSL --fail -C - --retry 3 -o "$DL/$name.part" "$url" && break
    echo "$(date +%T) 重试 $try $name"; sleep 10
  done
  got=$(stat -c %s "$DL/$name.part" 2>/dev/null || echo 0)
  if [ "$got" != "$size" ]; then echo "$(date +%T) SIZE_BAD $name $got != $size"; echo "$name $got - $repo@$rev SIZE_BAD" >> $LOG; continue; fi
  s=$(sha256sum "$DL/$name.part" | cut -d' ' -f1)
  if [ "$s" = "$sha" ]; then
    mkdir -p "$MODELS/$sub"; mv "$DL/$name.part" "$dest"; touch "$MODELS/$sub"
    echo "$name $size $s $repo@$rev OK" >> $LOG; echo "$(date +%T) OK $name"
  else
    echo "$name $size $s $repo@$rev SHA_BAD(want $sha)" >> $LOG; echo "$(date +%T) SHA_BAD $name"
  fi
done
echo "$(date +%T) DONE $PHASES"
