# IMGLAB P0 安装单（项目方 11-02 批准“允许装 P0 清单”，许可定性“目前非商用测试”）

执行脚本：tools/imglab/install_p0.sh（不重启）。代码由本机按 commit 检出、打包成 packs.tgz，经 tools/netfix/rsh.py 推到服务器；
权重在服务器上经代理 http://10.0.0.101:7190 从 HF 按 revision 下载，逐个核 sha256，不符即删。依赖 pip 全部带 constraints
（torch / numpy / opencv / transformers / onnxruntime / ultralytics 版本锁定），不装第二份 opencv，不装 sam2（git 版），
并在 custom_nodes/ 放 skip_download_model，禁止 Impact Pack / Subpack 的 install.py 自动下载 sam_vit_b（P1，未批准）。

## 机器

| 机器 | ComfyUI 根 | Python | 重启方式 | 范围 |
|---|---|---|---|---|
| gpu33 | /root/claude-kimi-ns-studio-v1/ComfyUI（8e3feba，10-28） | /root/claude-kimi-ns-studio-v1/env/comfy/bin/python | systemctl restart ns-comfy@0-8188 / @1-8189 / @3-8191 | 全部三道 |
| gpu36 | /root/work/fredw/comfy/ComfyUI | /root/work/fredw/venv/bin/python | /root/work/fredw/comfy/comfy.sh restart 0 | 只重启 gpu36:0；**gpu36:1 借给 cm_r2，不动**（节点等它归还后随下次重启生效）；gpu36:2 是看图卡 |

## 代码（custom_nodes/）

| 包 | 来源 | commit | 许可证 | 用途 |
|---|---|---|---|---|
| ComfyUI-Impact-Pack | https://github.com/ltdrdata/ComfyUI-Impact-Pack | 244e93ef9883aaf241d5d0e54ebb57e3b2e840d3（11-01，含 10-31 PR #1243 的 Qwen 2.1 修复） | GPL-3.0 | FaceDetailer / DetailerForEach / SEGS |
| ComfyUI-Impact-Subpack | https://github.com/ltdrdata/ComfyUI-Impact-Subpack | 50c7b71a6a224734cc9b21963c6d1926816a97f1 | AGPL-3.0 | UltralyticsDetectorProvider |
| ComfyUI-Inpaint-CropAndStitch | https://github.com/lquesada/ComfyUI-Inpaint-CropAndStitch | 6005efc02f7745649118edd89cdd084c2b9bd3ae | GPL-3.0 | 局部重绘裁切 / 贴回（未遮罩区不过 VAE） |
| comfyui_controlnet_aux | https://github.com/Fannovel16/comfyui_controlnet_aux | a587a4c1594524c1d2de5cd1a86cd868ff448e1c | Apache-2.0 | DWPose 预处理（不用 OpenPose 预处理器：CMU 权重非商用） |
| ComfyUI-qwen_img_2_1_enhancer | https://github.com/deng232/ComfyUI-qwen_img_2_1_enhancer | 1ae86cb87354b1da1780bc383c68496c72984084 | MIT | Reference Strength（逐张参考图注意力权重 / 遮罩） |
| ComfyUI-KJNodes | 两台已装（gpu33 ab72eda） | — | GPL-3.0 | ColorMatch（已有，不重装） |

## 权重

| 文件 | 来源（HF revision） | 大小 | sha256 | 许可证 | 目标 | 现状 |
|---|---|---|---|---|---|---|
| face_yolov8m.pt | Bingsu/adetailer@53cc19de | 52,026,019 | 717923c19b3f4bbf5250b728f1fa6b2cb72a33aed1d236ea9caf0e21ad943e5f | 卡 Apache-2.0（Ultralytics 主张 AGPL，争议） | models/ultralytics/bbox/ | 两台已有（脚本核 sha） |
| hand_yolov9c.pt | Bingsu/adetailer@53cc19de | 51,633,747 | 6f116f686ef5942fa0c1d08db481b3d7622047a97847eccfb2a264f9ce9777f2 | 同上 | models/ultralytics/bbox/ | 新 |
| person_yolov8m-seg.pt | Bingsu/adetailer@53cc19de | 54,827,683 | c8ab26f517173b1fe8342d336a09f443eb61cb08dcbfc78d53fff4c2547ae81e | 同上 | models/ultralytics/segm/ | 新 |
| yolox_l.onnx | yzd-v/DWPose@1a714410 | 216,746,733 | 7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411 | Apache-2.0 | custom_nodes/comfyui_controlnet_aux/ckpts/yzd-v/DWPose/ | 新 |
| dw-ll_ucoco_384.onnx | yzd-v/DWPose@1a714410 | 134,399,116 | 724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843 | Apache-2.0 | 同上 | 新 |
| qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors | Comfy-Org/Qwen-Image-2.1@aacf31a6 | 3,779,298,944 | 07aa961570ac0e03d4ca936aecd76854d077a33cde69b5092399afba01b3715d | Qwen Research License | models/model_patches/ | gpu33 已有（10-29，sha 一致）；gpu36 新 |

合计新下载：gpu33 约 0.46 GB；gpu36 约 4.2 GB。

## 步骤

1. 本机：按上表 commit 检出到隔离目录 → tar 成 packs.tgz → rsh 推到 /root/work/fredw/imglab_p0/（两台）。
2. 服务器：bash install_p0.sh <ROOT> <PY> /root/work/fredw/imglab_p0 → install.log 里每项 OK / FAIL / sha。
3. 重启（一次）：等该道队列连续空闲 ≥ 120 s 再重启（gpu33 三道逐道；gpu36 只 0 号）；重启后 /object_info 核节点：
   FaceDetailer、UltralyticsDetectorProvider、SAMLoader（可无模型）、InpaintCropImproved / InpaintStitchImproved、DWPreprocessor、
   ZImageFunControlnet、ModelPatchLoader、Reference Strength 节点。
4. 冒烟（各 1 张，单镜非成人）：Detailer（FaceDetailer + hand_yolov9c）、DWPose（从生产首帧提骨架）、Fun CN int8（姿势模板）→
   data/review_pages/imglab/smoke/，总调度亲审后才进 A/B。
5. 回退：删除上述 custom_nodes 目录与权重，pip 按 freeze.before.txt 还原，重启。
