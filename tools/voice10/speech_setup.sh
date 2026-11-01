#!/bin/bash
# VOICE10 11-01（K-EDT-022）：服务器常驻合成的本机配音环境（gpu33 / gpu36 各跑一次，幂等）。
# 与笔记本同一套：独立解释器只装 sherpa-onnx==1.13.8（本仓库不 import sherpa-onnx），Kokoro multi-lang v1.1 + SenseVoice int8。
# 路径与 config/voices.json 的 *_posix 键一致：
#   speech_python.default_posix  = /root/work/fredw/speech/venv/bin/python
#   tts_model.default_dir_posix  = /root/work/fredw/speech/models/kokoro-multi-lang-v1_1
#   asr_model.default_dir_posix  = /root/work/fredw/speech/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17
# 克隆音色（cosyvoice3_zs）仍在 gpu36 的 venv_tts 里跑：gpu36 上 OFFLINE_SELF=gpu36 → 本机执行（ns_post.tts.remote_is_local），
# gpu33 上经 ssh gpu36。只下载开源模型，不花钱、不删文件。用法：bash tools/voice10/speech_setup.sh
set -u
S=/root/work/fredw/speech
M=$S/models
mkdir -p $M
log() { echo "[speech_setup $(hostname)] $*"; }

# 1) 解释器
if [ ! -x $S/venv/bin/python ]; then
  PYB=$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)
  $PYB -m venv $S/venv || { log "venv 失败（$PYB）"; exit 1; }
fi
if ! $S/venv/bin/python -c "import sherpa_onnx,sys; sys.exit(0 if sherpa_onnx.__version__=='1.13.8' else 1)" 2>/dev/null; then
  $S/venv/bin/python -m pip install -q "sherpa-onnx==1.13.8" \
    || $S/venv/bin/python -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple "sherpa-onnx==1.13.8" \
    || { log "pip 安装 sherpa-onnx==1.13.8 失败"; exit 1; }
fi
log "sherpa-onnx $($S/venv/bin/python -c 'import sherpa_onnx;print(sherpa_onnx.__version__)')"

# 2) 模型：① 本机已有副本（gpu33 的旧 kimi 目录）→ cp；② hf-mirror（csukuangfj/<目录名>，实测比 GitHub 快）；
#    ③ k2-fsa 官方发布包（GitHub / ghproxy 镜像；gpu36 实测约 120 KB/s，最慢）
fetch() {  # $1 = 目录名  $2 = release tag  $3 = 必须存在的文件
  [ -f "$M/$1/$3" ] && { log "$1 已在"; return 0; }
  for src in /root/claude-kimi-ns-studio-v1/models/speech/$1; do
    if [ -f "$src/$3" ]; then cp -r "$src" "$M/$1.part" && mv "$M/$1.part" "$M/$1" && { log "$1 从 $src 复制"; return 0; }; fi
  done
  if [ -x /root/work/fredw/venv_tts/bin/python ] || $S/venv/bin/python -m pip install -q huggingface_hub; then
    HPY=$([ -x /root/work/fredw/venv_tts/bin/python ] && echo /root/work/fredw/venv_tts/bin/python || echo $S/venv/bin/python)
    log "hf-mirror csukuangfj/$1"
    HF_ENDPOINT=https://hf-mirror.com $HPY -c "import sys;from huggingface_hub import snapshot_download as d;d(sys.argv[1],local_dir=sys.argv[2])"       "csukuangfj/$1" "$M/$1.part" && [ -f "$M/$1.part/$3" ] && mv "$M/$1.part" "$M/$1" && { log "$1 就绪（hf-mirror）"; return 0; }
  fi
  local u="https://github.com/k2-fsa/sherpa-onnx/releases/download/$2/$1.tar.bz2"
  for url in "$u" "https://ghfast.top/$u" "https://gh-proxy.com/$u"; do
    log "下载 $url"
    if curl -sSfL --retry 3 --connect-timeout 30 -o "$M/$1.tar.bz2.part" "$url"; then
      mv "$M/$1.tar.bz2.part" "$M/$1.tar.bz2" && tar -xjf "$M/$1.tar.bz2" -C $M && [ -f "$M/$1/$3" ] && { log "$1 就绪"; return 0; }
    fi
  done
  log "$1 下载失败"; return 1
}
# SenseVoice（必需：成片对白回听）：本机副本 → hf-mirror 单文件（csukuangfj/…-2024-07-17 仓库里的 model.int8.onnx + tokens.txt，
# gpu36 实测约 2 MB/s）→ 官方发布包
SV=sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17
fetch_sv() {
  [ -f "$M/$SV/model.int8.onnx" ] && { log "$SV 已在"; return 0; }
  if [ -f /root/claude-kimi-ns-studio-v1/models/speech/$SV/model.int8.onnx ]; then fetch $SV asr-models model.int8.onnx; return $?; fi
  local h=https://hf-mirror.com/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main
  mkdir -p "$M/$SV.part" && curl -sSfL --retry 3 -o "$M/$SV.part/tokens.txt" $h/tokens.txt     && curl -sSfL --retry 3 -o "$M/$SV.part/model.int8.onnx" $h/model.int8.onnx && mv "$M/$SV.part" "$M/$SV"     && { log "$SV 就绪（hf-mirror）"; return 0; }
  fetch $SV asr-models model.int8.onnx
}
rc=0
fetch_sv || rc=1
# Kokoro（可选：series10 全部角色和旁白都是克隆音色，Kokoro 只在有 engine=kokoro 的说话人时才用；ns_post.tts 不再因缺它而失败）
if [ "${WITH_KOKORO:-auto}" = 1 ] || [ -d /root/claude-kimi-ns-studio-v1/models/speech/kokoro-multi-lang-v1_1 ]; then
  fetch kokoro-multi-lang-v1_1 tts-models voices.bin || log "Kokoro 未装（可选）"
fi
exit $rc
