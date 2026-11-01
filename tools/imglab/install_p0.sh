#!/bin/bash
# IMGLAB P0 安装（项目方 11-02 在 AskUserQuestion 点选“允许装 P0 清单”，总调度转；清单与来源见 docs/research/imglab/install_plan.md）。
# 只装代码 + 依赖 + 权重，不重启 ComfyUI（重启另走 restart 步骤，挑生产空档，K-OPS-R11 一次装完一次重启）。
# 用法: install_p0.sh <comfy_root> <python> <workdir>       （workdir 里已放 packs.tgz，由本机 tar 推上来）
set -u
ROOT=$1; PY=$2; W=$3
LOG=$W/install.log
PX="http://10.0.0.101:7190"
P="https_proxy=$PX http_proxy=$PX no_proxy=localhost,127.0.0.1,10.0.0.0/8"
cd "$W" || exit 1
echo "BEGIN $(date -Is) root=$ROOT py=$PY" >> $LOG
$PY -m pip freeze > freeze.before.txt 2>/dev/null
grep -iE '^(torch|torchvision|torchaudio|numpy|opencv-python-headless|opencv-python|opencv-contrib-python|pillow|scipy|triton|transformers|onnxruntime-gpu|onnxruntime|ultralytics)==' freeze.before.txt > constraints.txt
echo "constraints:" >> $LOG; cat constraints.txt >> $LOG

# 1) 代码：本机按 commit 检出、审读过的同一份字节（packs.tgz）；已存在的目录不覆盖
mkdir -p stage && tar -xzf packs.tgz -C stage
touch "$ROOT/custom_nodes/skip_download_model"     # Impact Pack / Subpack 的 install.py 会自动下 sam_vit_b（P1，未批准）→ 禁止
for n in ComfyUI-Impact-Pack ComfyUI-Impact-Subpack ComfyUI-Inpaint-CropAndStitch comfyui_controlnet_aux ComfyUI-qwen_img_2_1_enhancer; do
  if [ -e "$ROOT/custom_nodes/$n" ]; then echo "SKIP exists $n" >> $LOG; else cp -a "stage/$n" "$ROOT/custom_nodes/$n" && echo "COPIED $n" >> $LOG; fi
done

# 2) 依赖（全部带 constraints；不装第二份 opencv、不升级 torch / numpy；sam2 git 版不装——FaceDetailer 不需要）
inst() { env $P $PY -m pip install -c constraints.txt "$@" >> $LOG 2>&1 && echo "OK pip $*" >> $LOG || echo "FAIL pip $*" >> $LOG; }
inst segment-anything scikit-image piexif dill matplotlib
$PY -c "import ultralytics" 2>/dev/null || inst --no-deps "ultralytics>=8.3.162"
inst ultralytics-thop polars psutil
inst huggingface_hub filelock einops pyyaml python-dateutil omegaconf addict yacs trimesh rtree scikit-learn
inst --no-deps albumentationsx
inst mediapipe
$PY -c "import onnxruntime" 2>/dev/null || inst onnxruntime-gpu

# 3) 权重（经代理下 HF；逐个核 sha256，不符即删）
dl() {  # url dest sha
  local url=$1 dest=$2 sha=$3
  mkdir -p "$(dirname "$dest")"
  if [ -f "$dest" ] && [ "$(sha256sum "$dest" | cut -d' ' -f1)" = "$sha" ]; then echo "HAVE $dest" >> $LOG; return; fi
  env $P curl -sSL --retry 3 -o "$dest.part" "$url" && mv "$dest.part" "$dest"
  got=$(sha256sum "$dest" | cut -d' ' -f1)
  if [ "$got" = "$sha" ]; then echo "OK sha $dest $got" >> $LOG; else echo "FAIL sha $dest got=$got want=$sha" >> $LOG; rm -f "$dest"; fi
}
HF=https://huggingface.co
dl $HF/Bingsu/adetailer/resolve/53cc19de382014514d9d4038601d261a7faa9b7b/face_yolov8m.pt "$ROOT/models/ultralytics/bbox/face_yolov8m.pt" 717923c19b3f4bbf5250b728f1fa6b2cb72a33aed1d236ea9caf0e21ad943e5f
dl $HF/Bingsu/adetailer/resolve/53cc19de382014514d9d4038601d261a7faa9b7b/hand_yolov9c.pt "$ROOT/models/ultralytics/bbox/hand_yolov9c.pt" 6f116f686ef5942fa0c1d08db481b3d7622047a97847eccfb2a264f9ce9777f2
dl $HF/Bingsu/adetailer/resolve/53cc19de382014514d9d4038601d261a7faa9b7b/person_yolov8m-seg.pt "$ROOT/models/ultralytics/segm/person_yolov8m-seg.pt" c8ab26f517173b1fe8342d336a09f443eb61cb08dcbfc78d53fff4c2547ae81e
CK="$ROOT/custom_nodes/comfyui_controlnet_aux/ckpts/yzd-v/DWPose"
dl $HF/yzd-v/DWPose/resolve/1a7144101628d69ee7a3768d1ee3a094070dc388/yolox_l.onnx "$CK/yolox_l.onnx" 7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411
dl $HF/yzd-v/DWPose/resolve/1a7144101628d69ee7a3768d1ee3a094070dc388/dw-ll_ucoco_384.onnx "$CK/dw-ll_ucoco_384.onnx" 724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843
dl $HF/Comfy-Org/Qwen-Image-2.1/resolve/aacf31a6d48e707f352ecba714cee0680da3479b/model_patches/qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors \
   "$ROOT/models/model_patches/qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors" 07aa961570ac0e03d4ca936aecd76854d077a33cde69b5092399afba01b3715d

# 4) 导入自检（不起服务）：依赖能 import
$PY - >> $LOG 2>&1 <<'EOF'
import importlib
for m in ("segment_anything", "skimage", "piexif", "ultralytics", "mediapipe", "onnxruntime", "trimesh", "omegaconf"):
    try:
        importlib.import_module(m); print("IMPORTCHECK ok", m)
    except Exception as e:  # noqa: BLE001
        print("IMPORTCHECK FAIL", m, repr(e)[:200])
EOF
$PY -m pip freeze > freeze.after.txt 2>/dev/null
diff freeze.before.txt freeze.after.txt >> $LOG
echo "ALLDONE $(date -Is)" >> $LOG
