#!/bin/bash
# VOICE10 11-01（总调度方案 b，K-EDT-022）：在 gpu33 上复刻 gpu36 的克隆音色环境（venv_tts + cosy_overlay + CosyVoice 源码 + 模型），
# 两台服务器刻意不互相登录，所以版本靠“锁文件”从 gpu36 带到 gpu33（经笔记本，文本几 KB）：
#
#   gpu36：bash cosy_setup.sh capture  [LOCK_DIR]   → 写锁文件（python 版本、pip freeze、overlay freeze、CosyVoice commit、模型 revision）
#   笔记本：把 LOCK_DIR 拉回 tools/voice10/cosy_lock/（resident_sync push 会带到 gpu33）
#   gpu33：bash cosy_setup.sh install  [LOCK_DIR]   → 按锁文件装（幂等：已装的步骤跳过）
#   gpu33：bash cosy_setup.sh verify                 → CPU 上用一个说话人参考音频念一句，查出 24 kHz WAV
#   DRY=1 只打印要执行的命令。
#
# 版本 / 来源（与 gpu36 相同）：
#   模型 FunAudioLLM/Fun-CosyVoice3-0.5B-2512 @ 29e01c4e8d000f4bcd70751be16fa94bf3d85a18（config/voices.json remote_tts.model_dirs），
#   许可证 Apache-2.0（以模型卡为准，install 时把 LICENSE / README 头部记进 $BASE/venv_tts/MODEL_LICENSE.txt）；
#   源码 github.com/FunAudioLLM/CosyVoice（Apache-2.0）+ third_party/Matcha-TTS 子模块（MIT）；
#   transformers 4.51.3 叠加目录（cosyvoice3_zs 在 4.57.3 下输出乱码，RSI_LEDGER D15）。
# 下载走 hf-mirror / pypi 镜像 / ghfast 镜像，不花钱、不删文件。
set -u
MODE=${1:-}
HERE=$(cd "$(dirname "$0")" && pwd)
LOCK=${2:-$HERE/cosy_lock}
BASE=${COSY_BASE:-/root/work/fredw}
V=$BASE/venv_tts
SRC=$BASE/src_tts/CosyVoice
MODEL_REPO=FunAudioLLM/Fun-CosyVoice3-0.5B-2512
MODEL_REV_DEFAULT=29e01c4e8d000f4bcd70751be16fa94bf3d85a18
log() { echo "[cosy_setup $(hostname) $MODE] $*"; }
run() { if [ "${DRY:-0}" = 1 ]; then echo "DRY: $*"; else eval "$@"; fi; }

capture() {
  [ -x $V/bin/python ] || { log "没有 $V（capture 只在 gpu36 上跑）"; exit 1; }
  mkdir -p "$LOCK"
  $V/bin/python -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' > "$LOCK/python_version.txt"
  $V/bin/python -m pip freeze --exclude-editable | grep -v -E '^(-e |#)' > "$LOCK/venv_freeze.txt"
  if [ -d $V/cosy_overlay ]; then
    ls $V/cosy_overlay | sed -n 's/^\(.*\)-\([0-9][^-]*\)\.dist-info$/\1==\2/p' > "$LOCK/overlay_freeze.txt"
  fi
  (cd $SRC && git rev-parse HEAD) > "$LOCK/cosy_commit.txt" 2>/dev/null || echo unknown > "$LOCK/cosy_commit.txt"
  (cd $SRC && git submodule status 2>/dev/null) > "$LOCK/cosy_submodules.txt" || true
  ls $BASE/hf/hub/models--FunAudioLLM--Fun-CosyVoice3-0.5B-2512/snapshots/ > "$LOCK/model_revision.txt" 2>/dev/null || true
  # gpu36 实际用到的模型文件（19 个；仓库里第 20 个文件 gpu36 没下也能用）→ install 只下这些
  local snap; snap=$(ls -d $BASE/hf/hub/models--FunAudioLLM--Fun-CosyVoice3-0.5B-2512/snapshots/* 2>/dev/null | head -1)
  [ -n "$snap" ] && (cd "$snap" && find -L . -type f | sed 's#^\./##' | sort) > "$LOCK/model_files.txt"
  nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 > "$LOCK/driver.txt" 2>/dev/null || true
  log "锁文件写到 $LOCK：$(ls "$LOCK" | tr '\n' ' ')"
}

need_lock() {
  for f in python_version.txt venv_freeze.txt cosy_commit.txt; do
    [ -s "$LOCK/$f" ] || { log "缺锁文件 $LOCK/$f（先在 gpu36 上 capture 并拉回 tools/voice10/cosy_lock/）"; exit 1; }
  done
}

pick_python() {  # 与 gpu36 venv 同一个 major.minor
  local want; want=$(cut -d. -f1,2 "$LOCK/python_version.txt")
  for c in python$want /opt/anaconda3/bin/python$want /usr/bin/python$want $BASE/py$(echo $want | tr -d .)/bin/python$want; do
    command -v $c >/dev/null 2>&1 && { echo $c; return 0; }
  done
  # gpu36 的 venv 是 3.11（锁文件），gpu33 只有 3.10 / 3.12 → 用本机 anaconda 建一个同版本解释器（不动 base 环境）
  local full; full=$(cat "$LOCK/python_version.txt")
  local conda=/opt/anaconda3/bin/conda
  if [ -x $conda ]; then
    local P=$BASE/py$(echo $want | tr -d .)
    run "$conda create -y -q -p $P python=$full >&2 || $conda create -y -q -p $P -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main python=$full >&2"
    [ "${DRY:-0}" = 1 ] && { echo $P/bin/python$want; return 0; }
    [ -x $P/bin/python$want ] && { echo $P/bin/python$want; return 0; }
  fi
  return 1
}

pipi() {  # pip install，失败换清华镜像
  run "$V/bin/python -m pip install -q $* || $V/bin/python -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple $*"
}

install() {
  need_lock
  # 1) venv（同 python 版本）
  if [ ! -x $V/bin/python ]; then
    PYB=$(pick_python) || { log "本机没有 python$(cut -d. -f1,2 "$LOCK/python_version.txt")"; exit 1; }
    run "$PYB -m venv $V"
  fi
  # 2) 依赖：照 gpu36 的 freeze 装（torch 等 CUDA 轮子按 freeze 里的版本号；本地路径 / VCS 行跳过）
  if [ ! -f $V/.ns_freeze_ok ] || ! cmp -s "$LOCK/venv_freeze.txt" $V/.ns_freeze_ok; then
    # conda 本地构建的包（name @ file:///…）在 gpu36 是从 conda 带进来的：只留包名、不钉版本；git 源跳过
    grep -v -E ' @ git' "$LOCK/venv_freeze.txt" | sed -E 's/ @ file:.*$//' > /tmp/ns_cosy_req.txt
    local cu; cu=$(grep -o -m1 -E '^torch[a-z]*==[^+]+\+(cu[0-9]+)' /tmp/ns_cosy_req.txt | sed 's/.*+//')
    local extra=""; [ -n "$cu" ] && extra="--extra-index-url https://download.pytorch.org/whl/$cu"   # torch 的 CUDA 轮子
    if pipi "$extra -r /tmp/ns_cosy_req.txt"; then
      run "cp '$LOCK/venv_freeze.txt' $V/.ns_freeze_ok"
    else
      # 整份装不上（例：gpu36 上的 flib==0.2.23 在 PyPI 已没有）→ 逐个按原版本 --no-deps 装，装不上的记进 .ns_freeze_failed，
      # 不让一个缺包拖垮整套；最后 verify 真念一句才算数
      log "整份依赖安装失败，改逐个安装"
      run ": > $V/.ns_freeze_failed"
      while read -r req; do
        [ -n "$req" ] || continue
        pipi "--no-deps $extra '$req'" >/dev/null 2>&1 || run "echo '$req' >> $V/.ns_freeze_failed"
      done < /tmp/ns_cosy_req.txt
      log "逐个安装完成；装不上的：$(tr '\n' ' ' < $V/.ns_freeze_failed 2>/dev/null)"
      run "cp '$LOCK/venv_freeze.txt' $V/.ns_freeze_ok"
    fi
  else
    log "依赖已与锁文件一致"
  fi
  # 3) transformers 叠加目录（cosyvoice3_zs 专用）
  if [ -s "$LOCK/overlay_freeze.txt" ] && [ ! -f $V/cosy_overlay/.ns_ok ]; then
    run "mkdir -p $V/cosy_overlay"
    pipi "--no-deps --target $V/cosy_overlay $(tr '\n' ' ' < "$LOCK/overlay_freeze.txt")" && run "touch $V/cosy_overlay/.ns_ok"
  fi
  # 4) CosyVoice 源码（同 commit，含 Matcha-TTS 子模块）
  local commit; commit=$(cat "$LOCK/cosy_commit.txt")
  if [ ! -d $SRC/.git ]; then
    run "mkdir -p $(dirname $SRC)"
    run "git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git $SRC || git clone --recursive https://ghfast.top/https://github.com/FunAudioLLM/CosyVoice.git $SRC"
  fi
  if [ "$commit" != unknown ] && [ "$(cd $SRC 2>/dev/null && git rev-parse HEAD)" != "$commit" ]; then
    run "cd $SRC && git fetch -q origin && git checkout -q $commit && git submodule update --init --recursive"
  fi
  # 5) 模型（与 voices.json model_dirs 同一路径：HF 缓存布局 + 同一 revision）
  local rev; rev=$(head -1 "$LOCK/model_revision.txt" 2>/dev/null); rev=${rev:-$MODEL_REV_DEFAULT}
  # 不用“目录在不在”判断：上次中断会留下半截快照目录。snapshot_download 每次都跑，已下完的文件自动跳过；完成后打标记
  if [ ! -f $BASE/hf/hub/.ns_cosy3_$rev.ok ]; then
    # 有 model_files.txt 就只下 gpu36 实际在用的文件（11-01 gpu33 实测：全量下载卡在 gpu36 也没有的第 20 个文件上）
    local allow=""; [ -s "$LOCK/model_files.txt" ] && allow=",allow_patterns=[l.strip() for l in open('$LOCK/model_files.txt') if l.strip()]"
    run "HF_ENDPOINT=https://hf-mirror.com $V/bin/python -c \"from huggingface_hub import snapshot_download as d;print(d('$MODEL_REPO',revision='$rev',cache_dir='$BASE/hf/hub'$allow))\""
  fi
  local md=$BASE/hf/hub/models--FunAudioLLM--Fun-CosyVoice3-0.5B-2512/snapshots/$rev
  # 逐个核对 model_files.txt：缺的（11-01 gpu33：hf-mirror 对 CosyVoice-BlankEN/vocab.json 反复断连）改从 ModelScope 同名仓库补，
  # 全部齐了才打完成标记，verify 才有意义
  if [ ! -f $BASE/hf/hub/.ns_cosy3_$rev.ok ] && [ "${DRY:-0}" != 1 ]; then
    local miss=0
    if [ -s "$LOCK/model_files.txt" ]; then
      while read -r f; do
        [ -n "$f" ] && [ ! -e "$md/$f" ] || continue
        mkdir -p "$(dirname "$md/$f")"
        curl -sSfL --retry 3 -o "$md/$f.part" "https://www.modelscope.cn/models/$MODEL_REPO/resolve/master/$f" \
          && mv "$md/$f.part" "$md/$f" && log "从 ModelScope 补 $f" || { log "缺 $f"; miss=1; }
      done < "$LOCK/model_files.txt"
    fi
    [ $miss = 0 ] && [ -d "$md" ] && touch $BASE/hf/hub/.ns_cosy3_$rev.ok
  fi
  if [ -d "$md" ] && [ ! -f $V/MODEL_LICENSE.txt ]; then
    { echo "$MODEL_REPO @ $rev"; head -40 "$md/README.md" 2>/dev/null | grep -i -A3 licen; [ -f "$md/LICENSE" ] && head -5 "$md/LICENSE"; } > $V/MODEL_LICENSE.txt
  fi
  log "完成：$V（python $($V/bin/python -V 2>&1)），源码 $(cd $SRC 2>/dev/null && git rev-parse --short HEAD)，模型 $md"
}

verify() {
  local R=$BASE/offline_20261101/repo
  local ref=$R/data/assets/voices/narrator_qag/ref.wav
  [ -f "$ref" ] || { log "没有参考音频 $ref（等 resident_sync 推送）"; exit 1; }
  local md; md=$(ls -d $BASE/hf/hub/models--FunAudioLLM--Fun-CosyVoice3-0.5B-2512/snapshots/* 2>/dev/null | head -1)
  local reftext; reftext=$($V/bin/python -c "import json;print(json.load(open('$R/data/assets/voices/narrator_qag/voice.json'))['ref_text'])")
  local J=/tmp/ns_cosy_verify; mkdir -p $J
  $V/bin/python - "$J/request.json" "$md" "$ref" "$reftext" <<'PY'
import json, sys
p, md, ref, rt = sys.argv[1:5]
json.dump({"engine": "cosyvoice3_zs", "model_dir": md, "ref_wav": ref, "ref_text": rt, "seed": 20261031,
           "items": [{"text": "今天的事，我想再好好想一想。", "out": p.rsplit("/", 1)[0] + "/000.wav", "speed": 1.0}]},
          open(p, "w"), ensure_ascii=False)
PY
  sh $R/services/post/ns_post/remote/run_narrator.sh "$J/request.json" none 0 | tail -1
  $V/bin/python -c "import soundfile as sf;d,s=sf.read('$J/000.wav');print('verify', s, 'Hz', round(len(d)/s,2), 's');assert s==24000 and len(d)/s>1" \
    && log "verify 通过" || { log "verify 失败"; exit 1; }
}

case "$MODE" in
  capture) capture ;;
  install) install ;;
  verify) verify ;;
  *) echo "用法：bash cosy_setup.sh capture|install|verify [LOCK_DIR]"; exit 2 ;;
esac
