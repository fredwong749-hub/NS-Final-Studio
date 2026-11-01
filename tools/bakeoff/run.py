"""BAKEOFF（2026-10-31）：出图模型真人质感对决——固定、可复现的对照协议。以后有新模型：在 MODELS 里加一行，重跑 gen/score/page。

协议（docs/ep02_iter/image_bakeoff.md §2，GEN_CONTRACT v1 对齐）：
  - 8 个镜头（SHOTS）：林晚近景×2、特写×1、全身×1、男主单人×1、阿岚×1、双人×1、场景空镜×1，取自 series10_v1 first_frame_jobs.json。
  - 提示词：剧本原文内容不改；只做系统层处理：去掉旧参考图注释和已证伪触发词（lnwan_qi，契约 I8），旧系统后缀（奶油虚化/浓郁饱和，契约 I7 禁止）
    换成当前默认预设徕卡 S★ 后缀；按模型的参考写法（<imageN> / 图N）重写参考图注释。
  - 两组：contract = 契约输入（身份脸 > 造型设定图 > 场景，按模型槽位，I9）；text = 仅文字对照。没有参考槽的模型只跑 text。
  - 每组 2 个 seed；统一 1.5× 出图（1152×2016）→ lanczos 缩到 768×1344，不锐化（公平比较；S★ 的 USM 另算）。
  - 编辑对比（EDITS）：同一张不合格首帧做 3 个编辑任务，各编辑模型 2 seed，按交付尺寸出。
  - 质检 = 契约 Q1–Q7（score_srv.py）：Q1 ArcFace、Q2 造型颜色直方图代理、Q3 景别、Q4 质感（高频能量/纹理方差/Laplacian/饱和度/油光）、
    Q5 手/肢体可疑（mediapipe）、Q6 OCR、Q7 场景颜色直方图代理。Q2/Q7 是代理指标，REFLOCK 的实现出来后换。

子命令（笔记本）：prep → push → start（服务器 nohup gen+score）→ pull → page
  python tools/bakeoff/run.py prep            # 生成 data/ab/image_bakeoff/plan.json + 参考图打包 + preflight 表
  python tools/bakeoff/run.py push            # 推到 gpu36:/root/work/fredw/bakeoff/srv
  python tools/bakeoff/run.py start [--models a,b] [--kinds t2i,edit]
  python tools/bakeoff/run.py status
  python tools/bakeoff/run.py pull            # 只拉 results.json + 缩略图
  python tools/bakeoff/run.py page            # 写 data/review_pages/image_bakeoff/index.html + contact sheet（不自动打开：先给总调度审）
服务器上：python run.py gen --lanes 8188,8189,8190 ；/root/work/fredw/venv_idm/bin/python score_srv.py
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ON_SERVER = not hasattr(os, "startfile")
ROOT = HERE.parents[1] if not ON_SERVER else HERE          # 服务器上 srv/ 目录平铺
AB = (ROOT / "data/ab/image_bakeoff") if not ON_SERVER else HERE
PLAN = AB / "plan.json"
HOST, SRV = "gpu36", "/root/work/fredw/bakeoff/srv"
COMFY_IN = "/root/work/fredw/comfy/ComfyUI/input"
COMFY_OUT = "/root/work/fredw/comfy/output"
RUN = "data/pipeline/runs/series10_v1"

PW, PH = 768, 1344
BW, BH = 1152, 2016
SEEDS = [20261031, 20261131]
LEICA = "专业电影画面，徕卡M 50mm f/2镜头，焦点锐利，微反差强，皮肤纹理清晰，自然高光，暖调通透，干净真实"   # config/render_quality.json leica_sstar.style_suffix
TAIL = "无字幕、无文字、无水印"
NEG = "anime, cartoon, illustration, CGI, 3d render, doll face, plastic skin, deformed hands, extra fingers, text, subtitles, watermark, logo"
TURBO_SIGMAS = "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0"   # ns_render.workflows.TURBO_SIGMAS

# ---------------------------------------------------------------- 模型登记（加新模型 = 加一行）
# fam: 图构建族；slots: 参考槽数（0 = 只能纯文字）；tok: 提示词里引用参考图的写法；edit: 能否做编辑对比
MODELS = {
    "qwen21_sstar": dict(fam="qwen21", label="Qwen-Image 2.1 Turbo · 徕卡 S★（现行基线，去 lin_wan_qi）", slots=10, tok="图{n}", edit=True,
                         unet="qwen_image_2.1_turbo_int8_convrot.safetensors", clip="qwen3vl_8b_int8_convrot.safetensors",
                         vae="texture_fix_vae_for_qwen_image_2.1_bf16.safetensors", loras=[("krea2_film_texture_qwen21.safetensors", 0.5)],
                         license="Qwen Research License（仅非商用）"),
    "qwen21_v9_heavy": dict(fam="qwen21", label="Qwen-Image 2.1 Turbo · v9 重档（S★ 结构 + krea2 0.8；ASSETMASTER 全量重出配方 frame_v9_heavy）", slots=3,
                            tok="图{n}", edit=False, unet="qwen_image_2.1_turbo_int8_convrot.safetensors", clip="qwen3vl_8b_int8_convrot.safetensors",
                            vae="texture_fix_vae_for_qwen_image_2.1_bf16.safetensors", loras=[("krea2_film_texture_qwen21.safetensors", 0.8)],
                            license="Qwen Research License（仅非商用）"),
    # Qwen 2.1 调参 A/B（R11-12，docs/qwen21/RESEARCH.md；只跑契约组，与 qwen21_sstar 契约组同镜同种子对比）
    "qa_base": dict(fam="qwen21", label="Qwen 2.1 S★ · 本批基线（与 qa_* 同时出，同一身份脸 / 资产版本）", slots=10, tok="图{n}", edit=False,
                    unet="qwen_image_2.1_turbo_int8_convrot.safetensors", clip="qwen3vl_8b_int8_convrot.safetensors",
                    vae="texture_fix_vae_for_qwen_image_2.1_bf16.safetensors", loras=[("krea2_film_texture_qwen21.safetensors", 0.5)],
                    contract_only=True, license="Qwen Research License（仅非商用）"),
    "qa_imgtag": dict(fam="qwen21", label="Qwen 2.1 S★ · 参考写法 <imageN>（官方写法，RESEARCH 结论 2）", slots=10, tok="<image{n}>", edit=False,
                      unet="qwen_image_2.1_turbo_int8_convrot.safetensors", clip="qwen3vl_8b_int8_convrot.safetensors",
                      vae="texture_fix_vae_for_qwen_image_2.1_bf16.safetensors", loras=[("krea2_film_texture_qwen21.safetensors", 0.5)],
                      contract_only=True, license="Qwen Research License（仅非商用）"),
    "qa_native": dict(fam="qwen21", label="Qwen 2.1 S★ · 原生 9:16 尺寸 1536×2752（RESEARCH 结论 8）", slots=10, tok="图{n}", edit=False,
                      unet="qwen_image_2.1_turbo_int8_convrot.safetensors", clip="qwen3vl_8b_int8_convrot.safetensors",
                      vae="texture_fix_vae_for_qwen_image_2.1_bf16.safetensors", loras=[("krea2_film_texture_qwen21.safetensors", 0.5)],
                      render=[1536, 2752], contract_only=True, license="Qwen Research License（仅非商用）"),
    "qa_lora0": dict(fam="qwen21", label="Qwen 2.1 S★ · 不挂 krea2 LoRA（RESEARCH 结论 10：作者只在 base 上验证过）", slots=10, tok="图{n}",
                     edit=False, unet="qwen_image_2.1_turbo_int8_convrot.safetensors", clip="qwen3vl_8b_int8_convrot.safetensors",
                     vae="texture_fix_vae_for_qwen_image_2.1_bf16.safetensors", loras=[], contract_only=True,
                     license="Qwen Research License（仅非商用）"),
    "qa_suffix": dict(fam="qwen21", label="Qwen 2.1 S★ · 后缀去质量助推词、改写具体光线（RESEARCH 结论 7）", slots=10, tok="图{n}", edit=False,
                      unet="qwen_image_2.1_turbo_int8_convrot.safetensors", clip="qwen3vl_8b_int8_convrot.safetensors",
                      vae="texture_fix_vae_for_qwen_image_2.1_bf16.safetensors", loras=[("krea2_film_texture_qwen21.safetensors", 0.5)],
                      suffix="竖构图写实照片，50mm 镜头视角，自然光比，光从侧前方落在脸颊和发丝上形成真实的明暗过渡",
                      contract_only=True, license="Qwen Research License（仅非商用）"),
    "qa_all": dict(fam="qwen21", label="Qwen 2.1 S★ · 以上四项合并（<imageN> + 原生尺寸 + 无 LoRA + 新后缀）", slots=10, tok="<image{n}>",
                   edit=False, unet="qwen_image_2.1_turbo_int8_convrot.safetensors", clip="qwen3vl_8b_int8_convrot.safetensors",
                   vae="texture_fix_vae_for_qwen_image_2.1_bf16.safetensors", loras=[], render=[1536, 2752],
                   suffix="竖构图写实照片，50mm 镜头视角，自然光比，光从侧前方落在脸颊和发丝上形成真实的明暗过渡",
                   contract_only=True, license="Qwen Research License（仅非商用）"),
    # 社区写实 LoRA（R11-13，docs/qwen21/COMMUNITY_PHOTOREAL.md；gpu36 已有，sha 见 docs/ep02_iter/civitai_study.md；替换 krea2，作者推荐强度）
    "qa_lenovo": dict(fam="qwen21", label="Qwen 2.1 S★ · Lenovo UltraReal 0.7 替换 krea2（作者在 base cfg3–4 上推荐，Turbo 未验证）", slots=10,
                      tok="图{n}", edit=False, unet="qwen_image_2.1_turbo_int8_convrot.safetensors", clip="qwen3vl_8b_int8_convrot.safetensors",
                    vae="texture_fix_vae_for_qwen_image_2.1_bf16.safetensors", contract_only=True, loras=[("civitai/lenovo_qwen21.safetensors", 0.7)], license="Qwen Research（仅非商用）；LoRA 出图可商用"),
    "qa_niceasian": dict(fam="qwen21", label="Qwen 2.1 S★ · NiceGirls Asians 0.7 替换 krea2", slots=10, tok="图{n}", edit=False, unet="qwen_image_2.1_turbo_int8_convrot.safetensors", clip="qwen3vl_8b_int8_convrot.safetensors",
                    vae="texture_fix_vae_for_qwen_image_2.1_bf16.safetensors", contract_only=True,
                         loras=[("civitai/niceasians_qwen21.safetensors", 0.7)], license="Qwen Research（仅非商用）；LoRA 见 civitai_study"),
    "qa_grain": dict(fam="qwen21", label="Qwen 2.1 S★ · GrainScape 0.7 替换 krea2", slots=10, tok="图{n}", edit=False, unet="qwen_image_2.1_turbo_int8_convrot.safetensors", clip="qwen3vl_8b_int8_convrot.safetensors",
                    vae="texture_fix_vae_for_qwen_image_2.1_bf16.safetensors", contract_only=True,
                     loras=[("civitai/grainscape_qwen21.safetensors", 0.7)], license="Qwen Research（仅非商用）；LoRA 出图可商用"),
    "bb_2511_official": dict(fam="qedit", label="Qwen-Edit-2511 官方配方（40 步 cfg3、shift 3.1、CFGNorm，无 Lightning）", slots=3, tok="图{n}",
                             edit=False, unet="qwen_image_edit_2511_int8_convrot.safetensors", clip="qwen_2.5_vl_7b_fp8_scaled.safetensors",
                             vae="qwen_image_vae.safetensors", loras=[], steps=40, cfg=3.0, contract_only=True, license="Apache-2.0"),
    "krea2_turbo": dict(fam="krea2", label="Krea 2 Turbo（纯文字）", slots=0, tok="", edit=False,
                        unet="krea2_turbo_int8_convrot.safetensors", clip="qwen3vl_4b_int8_convrot.safetensors", vae="qwen_image_vae.safetensors",
                        steps=8, sampler="euler", sched="simple", license="Krea 2 Community（年收入<100 万美元可商用）"),
    "krea2_ref": dict(fam="krea2ref", label="Krea 2 Raw + Turbo LoRA 0.6 · 参考图（ganloss 07-08 advanced krea2 写法）", slots=3, tok="图{n}", edit=True,
                      unet="krea2_raw_int8_convrot.safetensors", clip="qwen3vl_4b_int8_convrot.safetensors", vae="qwen_image_vae.safetensors",
                      loras=[("krea2_turbo_lora_rank_64_bf16.safetensors", 0.6)], steps=8, sampler="res_multistep", sched="beta",   # ganloss 用 res_2s（RES4LYF 第三方采样器，没装）→ 原生最近的 res_multistep
                      license="Krea 2 Community"),
    "krea2_idedit": dict(fam="krea2id", label="Krea 2 Turbo + Identity Edit V2 / General Edit V2（comfyui-krea2edit 节点，项目方 10-31 批准）", slots=2,
                         tok="图{n}", edit=True, unet="krea2_turbo_int8_convrot.safetensors", clip="qwen3vl_4b_int8_convrot.safetensors",
                         vae="qwen_image_vae.safetensors", lora_id="krea2_identity_edit_v2.safetensors", lora_gen="krea2_general_edit_v2.safetensors",
                         steps=8, license="Krea 2 Community + LoRA 仅非商用（krea-2-identity-edit-v2-license）"),
    "zimage_turbo": dict(fam="zimage", label="Z-Image Turbo（纯文字，无参考槽）", slots=0, tok="", edit=False,
                         unet="z_image_turbo_int8_convrot.safetensors", clip="qwen_3_4b.safetensors", vae="ae.safetensors",
                         steps=9, cfg=1.0, sampler="res_multistep", sched="simple", shift=3.0, license="Apache-2.0"),
    "zimage_base": dict(fam="zimage", label="Z-Image Base（纯文字，无参考槽）", slots=0, tok="", edit=False,
                        unet="z_image_int8_convrot.safetensors", clip="qwen_3_4b.safetensors", vae="ae.safetensors",
                        steps=30, cfg=4.0, sampler="res_multistep", sched="simple", shift=3.0, license="Apache-2.0"),
    "klein4b": dict(fam="klein", label="FLUX.2 [klein] 4B（蒸馏 4 步，多参考）", slots=4, tok="图{n}", edit=True,
                    unet="flux-2-klein-4b.safetensors", clip="qwen_3_4b.safetensors", vae="flux2-vae.safetensors", steps=4, cfg=1.0,
                    license="Apache-2.0"),
    "klein4b_base": dict(fam="klein", label="FLUX.2 [klein] 4B Base（50 步 cfg4，多参考）", slots=4, tok="图{n}", edit=False,
                         unet="flux-2-klein-base-4b.safetensors", clip="qwen_3_4b.safetensors", vae="flux2-vae.safetensors", steps=50, cfg=4.0,
                         license="Apache-2.0"),
    "klein9b": dict(fam="klein", label="FLUX.2 [klein] 9B（蒸馏 4 步，多参考）", slots=4, tok="图{n}", edit=True,
                    unet="flux-2-klein-9b.safetensors", clip="qwen_3_8b_fp8mixed.safetensors", vae="flux2-vae.safetensors", steps=4, cfg=1.0,
                    license="FLUX Non-Commercial"),
    "klein9b_base": dict(fam="klein", label="FLUX.2 [klein] 9B Base（50 步 cfg4，多参考）", slots=4, tok="图{n}", edit=True,
                         unet="flux-2-klein-base-9b.safetensors", clip="qwen_3_8b_fp8mixed.safetensors", vae="flux2-vae.safetensors", steps=50,
                         cfg=4.0, license="FLUX Non-Commercial"),
    # 第 2 轮（总调度 11-01 批准，最低优先级）：Qwen 2.1 S★ 契约组出的首帧 → Klein 4B 第二段质感加工；脸部掩码保护，Q1 过才放行
    "r2_klein_d30_mask": dict(fam="refine", label="R2：Qwen 2.1 S★ → Klein 4B 质感加工（去噪 0.30，脸部掩码保护）", slots=0, tok="", edit=False,
                              unet="flux-2-klein-4b.safetensors", clip="qwen_3_4b.safetensors", vae="flux2-vae.safetensors", steps=8,
                              denoise=0.30, mask=True, src_model="qwen21_sstar", license="Apache-2.0（第一段 Qwen 2.1 仅非商用）"),
    "r2_klein_d45_mask": dict(fam="refine", label="R2：Qwen 2.1 S★ → Klein 4B 质感加工（去噪 0.45，脸部掩码保护）", slots=0, tok="", edit=False,
                              unet="flux-2-klein-4b.safetensors", clip="qwen_3_4b.safetensors", vae="flux2-vae.safetensors", steps=8,
                              denoise=0.45, mask=True, src_model="qwen21_sstar", license="Apache-2.0（第一段 Qwen 2.1 仅非商用）"),
    "r2_klein_d30_nomask": dict(fam="refine", label="R2 对照：同上去噪 0.30，不保护脸（看脸会不会被改掉）", slots=0, tok="", edit=False,
                                unet="flux-2-klein-4b.safetensors", clip="qwen_3_4b.safetensors", vae="flux2-vae.safetensors", steps=8,
                                denoise=0.30, mask=False, src_model="qwen21_sstar", license="Apache-2.0（第一段 Qwen 2.1 仅非商用）"),
    "qedit2511": dict(fam="qedit", label="Qwen-Image-Edit-2511 + Lightning 4 步", slots=3, tok="图{n}", edit=True,
                      unet="qwen_image_edit_2511_int8_convrot.safetensors", clip="qwen_2.5_vl_7b_fp8_scaled.safetensors", vae="qwen_image_vae.safetensors",
                      loras=[("Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors", 1.0)], steps=4, license="Apache-2.0"),
    "firered11": dict(fam="qedit", label="FireRed-Image-Edit 1.1 fp8 + Lightning 8 步", slots=3, tok="图{n}", edit=True,
                      unet="firered_image_edit_1.1_fp8_scaled_e4m3fn.safetensors", clip="qwen_2.5_vl_7b_fp8_scaled.safetensors",
                      vae="qwen_image_vae.safetensors", loras=[("FireRed-Image-Edit-1.1-Lightning-8steps-v1.2.safetensors", 1.0)], steps=8,
                      license="Apache-2.0"),
}

FACE_MODE = {"qwen21_sstar", "klein4b", "klein9b", "qedit2511"}      # 加跑“只给身份脸”组的主力候选
ONE_SEED = {"zimage_base", "klein4b_base", "klein9b_base"}            # 50 步 base 只跑 1 个 seed（时间）
R2_PREFIX = "图1是本镜已定的首帧：构图、人物、脸、发型、服装、光线和背景都保持不变，只把皮肤与材质的质感改成真实摄影（可见细小毛孔与细软绒毛、自然的明暗过渡、不磨皮、不油亮）。"
# 出图顺序：先跑快的、项目方点名的；50 步的 base 放最后
PRIORITY = ["qwen21_sstar", "krea2_turbo", "zimage_turbo", "klein4b", "qedit2511", "krea2_idedit", "krea2_ref", "firered11", "klein9b",
            "zimage_base", "klein4b_base", "klein9b_base", "qwen21_v9_heavy",
            "r2_klein_d30_mask", "r2_klein_d45_mask", "r2_klein_d30_nomask",
            "qa_base", "qa_imgtag", "qa_native", "qa_lenovo", "qa_niceasian", "qa_grain", "bb_2511_official", "qa_lora0", "qa_suffix", "qa_all"]

# ---------------------------------------------------------------- 镜头与资产（契约 I1–I5）
FACE = {"lin_wan": "assets/characters/lin_wan/refs/lin_wan/ar-c2351c9dcf.png",       # 项目方通过的母版（脸部裁切）
        "gu_chen": "data/assets/identity_refs/gu_chen/gu_chen_face_ref2va.png",
        "chen_yu": "data/assets/identity_refs/chen_yu/chen_yu_face_ref2va.png",
        "ch_a_lan": "data/assets/identity_refs/ch_a_lan/ch_a_lan_face_ref2va.png"}
SCORE_FACE = {"lin_wan": ["data/assets/identity_refs/lin_wan/lin_wan_face_ref2va.png"],          # 与 IMGGEN 同参考，数字可直接对比
              "gu_chen": ["data/assets/identity_refs/gu_chen/gu_chen_face_ref2va.png"],
              "chen_yu": ["data/assets/identity_refs/chen_yu/chen_yu_face_ref2va.png"],
              # P1 唯一身份脸（REFLOCK 11-01）：与旧 sheets/ch_a_lan_face_ref.png 内容相同，统一用这一张
              "ch_a_lan": ["data/assets/identity_refs/ch_a_lan/ch_a_lan_face_ref2va.png"]}
SHEET = lambda c, look: f"{RUN}/images/sheets/{c}/" + {"lin_wan_A": "lin_wan_lookA_s202.png", "lin_wan_B": "lin_wan_lookB_s202.png",  # noqa: E731
                                                       "gu_chen_A": "gu_chen_lookA_s101.png", "gu_chen_B": "gu_chen_lookB_s101.png",
                                                       "ch_a_lan_A": "ch_a_lan_lookA_s1108.png"}[f"{c}_{look}"]
SCN_OFFICE = "assets/scenes/sk_office/refs/gen/ag-912c0cd085_s8207.png"
SCN_CLOSET = "assets/scenes/sk_gu_chen_closet/versions/sk_gu_chen_closet_main_v1.png"
NAMES = {"lin_wan": "林晚", "gu_chen": "顾沉", "chen_yu": "陈宇", "ch_a_lan": "阿岚"}
# id, 源镜头, 类别, 在画角色（主体在前）, 造型, 场景参考（None = 场景缺图，契约 I5 记“缺”）
SHOTS = [
    ("B1", "ep01-S5", "林晚单人·近景", ["lin_wan"], {"lin_wan": "A"}, SCN_OFFICE),
    ("B2", "ep10-S4", "林晚单人·中近景", ["lin_wan"], {"lin_wan": "B"}, None),
    ("B3", "ep01-S1", "林晚单人·特写", ["lin_wan"], {"lin_wan": "A"}, SCN_OFFICE),
    ("B4", "ep01-S3", "林晚单人·中全景（全身）", ["lin_wan"], {"lin_wan": "A"}, SCN_OFFICE),
    ("B5", "ep09-S2", "男主单人·中景（顾沉）", ["gu_chen"], {"gu_chen": "B"}, SCN_CLOSET),
    ("B6", "ep05-S2", "阿岚单人·特写", ["ch_a_lan"], {"ch_a_lan": "A"}, None),
    ("B7", "ep01-S6", "双人·中近景（顾沉+林晚）", ["lin_wan", "gu_chen"], {"lin_wan": "A", "gu_chen": "A"}, SCN_OFFICE),
    ("B8", "ep01-S1", "场景空镜·深夜写字楼办公区角落", [], {}, SCN_OFFICE),
]
EDIT_SRC = f"{RUN}/images/frames/ep05/ep05-S5_s20262612.png"     # IMGGEN 判不合格（林晚 0.534，对他人 0.518）+ 项目方说的塑料/油
EDITS = [
    ("E1", "换脸", "把{s}中女子的脸换成{r1}这个人的脸（只换脸部五官和发型，保持{s}的构图、姿势、手、服装、光线和背景完全不变）",
     ["lin_wan_face"]),
    ("E2", "去油光加毛孔", "去掉{s}中人物皮肤上的油光和塑料感，改成真实人像摄影的皮肤：可见细小毛孔、细软绒毛和自然的轻微不均匀，"
     "高光柔和不发亮；构图、人物、五官、服装和背景保持不变", []),
    ("E3", "换背景", "把{s}的背景换成{r1}这个深夜办公室场景（同样的光线方向和色温），人物、姿势、服装和前景保持不变", ["office"]),
]
EDIT_REF = {"lin_wan_face": FACE["lin_wan"], "office": SCN_OFFICE}


def leica(p: str) -> str:
    return p.rstrip("，。, ") + "，" + LEICA + "，" + TAIL


def clean_prompt(p: str) -> str:
    """系统层清理：不改剧本内容。去旧参考注释 / lnwan_qi 触发词 / 旧系统后缀（从“专业电影镜头画面感”起），换 S★ 后缀。"""
    p = re.sub(r"^(图\d+是[^。]*。)+", "", p)
    p = p.replace("lnwan_qi，", "").replace("lnwan_qi", "")
    for cut in ("专业电影镜头画面感", "专业电影画面，徕卡"):       # 旧后缀 / 作业里已带的 S★ 后缀都切掉，统一由 leica() 补一次
        i = p.find(cut)
        if i > 0:
            p = p[:i]
    return leica(p)


def ref_lines(refs: list[dict], tok: str) -> str:
    out = []
    for n, r in enumerate(refs, 1):
        t = tok.format(n=n)
        if r["role"] == "face":
            out.append(f"{t}是{r['name']}的脸部参考（只取脸和发型），{r['name']}的脸必须与{t}一致。")
        elif r["role"] == "sheet":
            out.append(f"{t}是{r['name']}本镜造型的设定图（服装、鞋、饰品必须与{t}一致，不取其中的姿势和背景）。")
        elif r["role"] == "scene":
            out.append(f"{t}是本镜场景参考（空间布局、陈设和光线基线与{t}一致）。")
    return "".join(out)


def plan_slots(chars, looks, scene, nslot, fam=""):
    """契约 I9：身份脸 > 造型设定图 > 场景；槽位不足就按优先级截断；两张脸各占一槽（不拼进同一槽）。"""
    want = [dict(role="face", char=c, name=NAMES[c], path=FACE[c]) for c in chars]
    want += [dict(role="sheet", char=c, name=NAMES[c], path=SHEET(c, looks[c])) for c in chars if c in looks]
    if scene:
        want.append(dict(role="scene", char=None, name="场景", path=scene))
    if fam == "krea2id":     # 节点只有两个参考口：a=场景（aligned）、b=人物（beside）；造型设定图放不进（会把设定图版式钉进画面）→ 记为 dropped
        face = [w for w in want if w["role"] == "face"][:1]
        sc = [w for w in want if w["role"] == "scene"]
        keep = sc + face
        return keep, [w["role"] + (":" + w["char"] if w["char"] else "") for w in want if w not in keep]
    return want[:nslot], [w["role"] + (":" + w["char"] if w["char"] else "") for w in want[nslot:]]


def prep():
    jobs = {j["shot"]: j for j in json.loads((ROOT / RUN / "assets/first_frame_jobs.json").read_text(encoding="utf-8"))["jobs"]}
    items, pre = [], []
    sys.path.insert(0, str(ROOT / "services/agent"))
    sys.path.insert(0, str(ROOT / "tools/pipeline"))
    from ns_agent.asset_refs import face_of, plan_for, record    # REFLOCK
    for c in list(FACE):                                  # 身份脸统一从资产中心取（face_overrides > config faces），取不到才用默认
        FACE[c] = face_of("series10_v1", c) or FACE[c]   # REFLOCK 资产参考解析器（契约 I2–I5、I9）
    rec_cache, casts, shot_rec = {}, {}, {}
    script = json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8"))
    for sid, src, cat, chars, looks, scene in SHOTS:
        j = jobs[src]
        epn, shn = int(src[2:4]), int(src.split("-S")[1])
        ep = next(e for e in script["episodes"] if e["number"] == epn)
        shot = next(x for x in ep["shots"] if x["index"] == shn)
        casts[src] = shot.get("cast") or []
        if chars and sid != "B8":                # 每镜一份完整资产记录（最大 4 槽），给本机 postflight 的 Q2 / Q7 用（各组同一标准）
            _sr, _pl = plan_for("series10_v1", ep, shot, capacity=4)
            shot_rec[sid] = record(_sr, _pl)
        if sid == "B8":                                      # 空镜：用 ep01-S1 的【场景】段，景别首句由系统模板给
            m = re.search(r"【场景】(.*?)(，面部清晰对焦|，专业电影镜头画面感)", j["prompt"])
            body = "空镜构图，画面中没有任何人物，" + m.group(1)
            base, size = leica(body), "空镜"
        else:
            base, size = clean_prompt(j["prompt"]), j["size"]
        for mk, m in MODELS.items():
            if m["fam"] == "refine":
                src_id = f"{sid}_{m['src_model']}_contract_{SEEDS[0]}"
                items.append(dict(id=f"{sid}_{mk}_r2_{SEEDS[0]}", kind="t2i", shot=sid, src=src, cat=cat, size=size, chars=chars,
                                  looks={c: SHEET(c, lk) for c, lk in looks.items()}, scene=scene, model=mk, mode="r2", seed=SEEDS[0],
                                  prompt=R2_PREFIX + base, refs=[], ref_roles=["stage1"], dropped=[], stage1=src_id,
                                  preflight={"ok": True, "note": "第二段加工：输入 = 已过 preflight 的第一段首帧（同镜契约组），不新挂参考 / LoRA"}))
                continue
            if m["slots"] == 0 or not (chars or scene):
                modes = ["text"]
            elif m["fam"] == "krea2id" or mk == "qwen21_v9_heavy" or m.get("contract_only"):
                modes = ["contract"]
            else:
                modes = ["text", "contract"] + (["face"] if mk in FACE_MODE and chars else [])
            for mode in modes:
                dropped, board = [], None
                if mode == "text":
                    refs, prefix = [], ""
                elif mode == "face":                     # 无资产参考 = 只给身份脸，服装靠文字（REFLOCK 要求的对照组）
                    refs = [dict(role="face", path=FACE[c]) for c in chars][: m["slots"]]
                    prefix = "".join(f"图{n}是{NAMES[c]}的脸部参考（只取脸和发型），{NAMES[c]}的脸必须与图{n}一致。" for n, c in enumerate(chars[: m["slots"]], 1))
                elif sid == "B8":
                    rr, dropped = plan_slots(chars, looks, scene, m["slots"], m["fam"])
                    refs, prefix = [dict(role=r["role"], path=r["path"]) for r in rr], ref_lines(rr, "图{n}")
                else:                                    # 有资产参考 = REFLOCK plan_for（脸 + 去头设定图 / 参考板 + 单品 + 场景，按槽位）
                    _, pl = plan_for("series10_v1", ep, shot, capacity=m["slots"])
                    refs = [dict(role=sl.kind, path=f) for sl, f in zip(pl.slots, pl.files)]
                    prefix = pl.prompt_prefix
                    rec_cache[(sid, mk)] = record(_, pl)
                    dropped = [str(x) for x in (getattr(pl, "dropped", None) or [])]
                tok = m["tok"]
                prefix = re.sub(r"图(\d+)", lambda mm: tok.format(n=mm.group(1)), prefix) if tok else prefix
                for seed in (SEEDS[:1] if mk in ONE_SEED else SEEDS):
                    items.append(dict(id=f"{sid}_{mk}_{mode}_{seed}", kind="t2i", shot=sid, src=src, cat=cat, size=size, chars=chars,
                                      looks={c: SHEET(c, lk) for c, lk in looks.items()}, scene=scene, model=mk, mode=mode, seed=seed,
                                      prompt=prefix + (base.replace(LEICA, m["suffix"]) if m.get("suffix") else base), refs=[r["path"] for r in refs], ref_roles=[r["role"] for r in refs], dropped=dropped))
            pre.append(dict(shot=sid, model=mk, I1=bool(chars) or sid == "B8", I2=all(c in FACE for c in chars),
                            I3=all(c in looks for c in chars), I4="REFLOCK plan_for（衣橱单品图 > 设定图裁切）" if chars else "不适用",
                            I5=bool(scene), I6="系统清理（去旧注释/触发词/旧后缀）+ 按模型写法重标参考图", I7="徕卡 S★ 后缀",
                            I8="无 LoRA" if not m.get("loras") else ",".join(x[0] for x in m["loras"]),
                            I9=f"槽 {m['slots']}", I10="成年设定（剧本标注年龄），非真实人物"))
    for sid, src, cat, chars, looks, scene in SHOTS:       # 现行出图（IMGGEN 的 series10 首帧，被项目方判"塑料/油/糊"）当已知差的参照
        if sid == "B8":
            continue
        prod = jobs[src]["out"]
        if (ROOT / prod).exists():
            items.append(dict(id=f"{sid}_prod_current_0", kind="prod", shot=sid, src=src, cat=cat, size=jobs[src]["size"], chars=chars,
                              looks={c: SHEET(c, lk) for c, lk in looks.items()}, scene=scene, model="prod_current", mode="现行",
                              seed=jobs[src].get("seed"), prompt=jobs[src]["prompt"], refs=[], ref_roles=[], dropped=[], path=prod))
    # IMGGEN 修 2.1 配方那条线的候选（imgfix，含 S★ 的 1.5× + USM 锐化后处理；本线所有模型都不锐化 → 高频类指标对它偏有利，页上标注）
    fixd = ROOT / RUN / "images/imgfix"
    for sid, src, cat, chars, looks, scene in SHOTS:
        for vid, lab in (("v10", "IMGGEN S★+脸+去头造型图（写实·中，含锐化）"), ("vR", "IMGGEN REFLOCK 资产槽位 S★（含锐化）")):
            f = fixd / src / f"{vid}_post.png"
            if f.exists():
                items.append(dict(id=f"{sid}_imggen_{vid}_0", kind="prod", shot=sid, src=src, cat=cat, size=jobs[src]["size"], chars=chars,
                                  looks={c: SHEET(c, lk) for c, lk in looks.items()}, scene=scene, model=f"imggen_{vid}", mode=lab, seed=None,
                                  prompt="", refs=[], ref_roles=[], dropped=[], path=str(f.relative_to(ROOT)).replace("\\", "/")))
    for eid, name, tpl, extra in EDITS:
        for mk, m in MODELS.items():
            if not m["edit"]:
                continue
            refs = [EDIT_SRC] + [EDIT_REF[x] for x in extra]
            t = [m["tok"].format(n=n) for n in range(1, len(refs) + 1)]
            prompt = tpl.format(s=t[0], r1=t[1] if len(t) > 1 else "")
            for seed in SEEDS:
                items.append(dict(id=f"{eid}_{mk}_{seed}", kind="edit", shot=eid, src=EDIT_SRC, cat=name, size="大特写", chars=["lin_wan"],
                                  looks={}, scene=SCN_OFFICE if eid == "E3" else None, model=mk, mode="edit", seed=seed, prompt=prompt,
                                  refs=refs, ref_roles=["source"] + extra, dropped=[]))
    # 契约 preflight（GEN_CONTRACT §0.1）：contract 组必须过才算正式参赛；text / face 组是刻意缺资产的对照，记录不阻断
    from ns_agent.gen_contract import preflight
    from image_jobs import contract_request
    MODEL_KEY = {"qwen21": "qwen_image_2.1", "qedit": "qwen_image_edit_2511", "klein": "flux2_klein"}
    for it in items:
        if it["kind"] != "t2i" or it["shot"] == "B8" or it.get("stage1"):
            continue
        m = MODELS[it["model"]]
        req = contract_request(jobs[it["src"]])
        if m.get("suffix"):
            req["suffix_variant"] = it["model"]            # REFLOCK 11-01：scope=bakeoff + suffix_variant 才允许换后缀（禁用词照查）
        req.update(scope="bakeoff", model=MODEL_KEY.get(m["fam"], it["model"]), prompt=it["prompt"], refs=it["refs"], loras=[list(x) for x in m.get("loras") or []],
                   compiled_by=jobs[it["src"]].get("compiled_by", "") + " + tools/bakeoff 系统清理（去旧注释/触发词/旧后缀，换 S★ 后缀，REFLOCK 标注）",
                   cast=req.get("cast") or casts.get(it["src"]) or [],
                   asset_refs=rec_cache.get((it["shot"], it["model"])) if it["mode"] == "contract" else None)
        try:
            r = preflight("image", req)
            d = r.to_dict() if hasattr(r, "to_dict") else r
            it["preflight"] = {"ok": d.get("ok"), "fail": [x for x in d.get("items", []) if x.get("status") == "fail"]}
        except Exception as e:  # noqa: BLE001
            it["preflight"] = {"ok": False, "error": str(e)[:300]}
    files = sorted({p for it in items for p in it["refs"]} | {p for v in SCORE_FACE.values() for p in v} | {EDIT_SRC}
                   | {p for it in items for p in it["looks"].values()} | {SCN_OFFICE, SCN_CLOSET}
                   | {it["path"] for it in items if it["kind"] == "prod"})
    missing = [f for f in files if not (ROOT / f).exists()]
    AB.mkdir(parents=True, exist_ok=True)
    gc = json.loads((ROOT / "config/gen_contract.json").read_text(encoding="utf-8"))
    plan = dict(created=time.strftime("%Y-%m-%d %H:%M"), models=MODELS, lora_allow=sorted(set(gc.get("lora_allow") or {}) | set((gc.get("lora_allow_scoped") or {}).get("bakeoff") or {})), seeds=SEEDS, render=[BW, BH], out=[PW, PH], score_face=SCORE_FACE, shot_rec=shot_rec, casts=casts,
                items=items, preflight=pre, files=files, missing=missing)
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"plan: {len(items)} 张（t2i {sum(i['kind'] == 't2i' for i in items)} / edit {sum(i['kind'] == 'edit' for i in items)}），参考文件 {len(files)}，缺 {missing}")


def push():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for f in ("run.py", "score_srv.py"):
            t.add(HERE / f, arcname=f)
        t.add(PLAN, arcname="plan.json")
        t.add(ROOT / "tools/series10_imggen/hands_remote.py", arcname="hands_remote.py")
        have = set(subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, f"cd {SRV}/refs 2>/dev/null && find . -type f -printf '%P\n'"],
                                  capture_output=True, text=True).stdout.split())
        for f in json.loads(PLAN.read_text(encoding="utf-8"))["files"]:
            if f in have:                      # 只推服务器上还没有的参考图（笔记本上行慢）
                continue
            if "/images/sheets/" in f:          # 造型设定图只用于 Q2 打分（模型输入用 REFLOCK 的去头裁切）→ JPEG q90 内容，省上行
                from PIL import Image
                b = io.BytesIO()
                Image.open(ROOT / f).convert("RGB").save(b, "JPEG", quality=90)
                ti = tarfile.TarInfo("refs/" + f)
                ti.size = len(b.getvalue())
                b.seek(0)
                t.addfile(ti, b)
            else:
                t.add(ROOT / f, arcname="refs/" + f)
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, f"mkdir -p {SRV} && cd {SRV} && tar xzf - && echo PUSH_OK"],
                       input=buf.getvalue(), capture_output=True)
    print(f"{len(buf.getvalue()) / 1e6:.1f} MB", (r.stdout + r.stderr).decode(errors="replace").strip()[-300:])


# ---------------------------------------------------------------- 服务器：出图
class G(dict):
    def add(self, ct, **inp):
        k = str(len(self) + 1)
        self[k] = {"class_type": ct, "inputs": inp}
        return [k, 0]


def load_img(g, name, mp=None):
    im = g.add("LoadImage", image=name)
    return g.add("ImageScaleToTotalPixels", image=im, upscale_method="lanczos", megapixels=mp, resolution_steps=16) if mp else im


def with_loras(g, model, loras):
    for n, s in loras or []:
        model = g.add("LoraLoaderModelOnly", model=model, lora_name=n, strength_model=s)
    return model


def build(it, m, names, prefix):
    g = G()
    W, H = (PW, PH) if it["kind"] == "edit" else tuple(m.get("render") or (BW, BH))
    seed, prompt = it["seed"], it["prompt"]
    fam = m["fam"]
    model = with_loras(g, g.add("UNETLoader", unet_name=m["unet"], weight_dtype="default"), m.get("loras"))
    vae = g.add("VAELoader", vae_name=m["vae"])
    if fam == "qwen21":
        clip = g.add("CLIPLoader", clip_name=m["clip"], type="qwen_image", device="default")
        enc = g.add("TextEncodeQwenImage21", clip=clip, prompt=prompt, negative_prompt=NEG, resolution=0, vae=vae,
                    **{f"images.image_{i}": load_img(g, n) for i, n in enumerate(names, 1)})
        pos, neg = enc, [enc[0], 1]
        lat = g.add("EmptyLatentImage", width=W, height=H, batch_size=1)
        guider = g.add("CFGGuider", model=model, positive=pos, negative=neg, cfg=1.0)
        sig = g.add("ManualSigmas", sigmas=TURBO_SIGMAS)
        out = g.add("SamplerCustomAdvanced", noise=g.add("RandomNoise", noise_seed=seed), guider=guider,
                    sampler=g.add("KSamplerSelect", sampler_name="euler"), sigmas=sig, latent_image=lat)
    elif fam in ("krea2", "krea2ref", "zimage", "qedit"):
        ctype = {"krea2": "krea2", "krea2ref": "krea2", "zimage": "lumina2", "qedit": "qwen_image"}[fam]
        clip = g.add("CLIPLoader", clip_name=m["clip"], type=ctype, device="default")
        if fam in ("krea2ref", "qedit") and names:
            imgs = {f"image{i}": load_img(g, n, 1.0) for i, n in enumerate(names, 1)}
            pos = g.add("TextEncodeQwenImageEditPlus", clip=clip, prompt=prompt, vae=vae, **imgs)
        else:
            pos = g.add("CLIPTextEncode", clip=clip, text=prompt)
        cfg = m.get("cfg", 1.0)
        neg = g.add("CLIPTextEncode", clip=clip, text=NEG) if cfg > 1 else g.add("ConditioningZeroOut", conditioning=pos)
        if fam == "zimage":
            model = g.add("ModelSamplingAuraFlow", model=model, shift=m["shift"])
        if fam == "qedit":
            model = g.add("CFGNorm", model=g.add("ModelSamplingAuraFlow", model=model, shift=3.1 if m.get("cfg", 1.0) > 1 else 3.0), strength=1.0)
        lat = g.add("EmptySD3LatentImage", width=W, height=H, batch_size=1)
        out = g.add("KSampler", model=model, seed=seed, steps=m.get("steps", 8), cfg=cfg, sampler_name=m.get("sampler", "euler"),
                    scheduler=m.get("sched", "simple"), positive=pos, negative=neg, latent_image=lat, denoise=1.0)
    elif fam == "krea2id":
        # 写法按 conradlocke/krea2-identity-edit README（V2）与 ganloss 07-27 v1.2 工作流：Turbo 8 步 cfg1，grounding 768；
        # 两图时 a=场景/原图（aligned），b=人物/身份（beside），ref_boost 落在 b；纯编辑（无身份）用 General Edit V2，ref_boost 4 落在原图。
        roles = it["ref_roles"]
        use_id = "face" in roles or "lin_wan_face" in roles
        model = g.add("LoraLoaderModelOnly", model=model, lora_name=m["lora_id"] if use_id else m["lora_gen"], strength_model=1.0)
        clip = g.add("CLIPLoader", clip_name=m["clip"], type="krea2", device="default")
        imgs = [load_img(g, n) for n in names]
        if it["kind"] == "t2i" and "face" in roles and len(imgs) > 1:      # 人物（脸）放最后一口 = 节点约定的 subject，ref_boost 落在它
            k = roles.index("face")
            imgs = [x for i, x in enumerate(imgs) if i != k] + [imgs[k]]
        lat = g.add("EmptySD3LatentImage", width=W, height=H, batch_size=1)
        if not imgs:
            pos = g.add("CLIPTextEncode", clip=clip, text=prompt)
        else:
            a, b = (imgs[0], imgs[1]) if len(imgs) > 1 else (imgs[0], None)
            enc = dict(clip=clip, prompt=prompt, image=a, grounding_px=768)
            if b is not None:
                enc["image_b"] = b
            pos = g.add("Krea2EditGroundedEncode", **enc)
            pat = dict(model=model, source_latent=g.add("VAEEncode", pixels=a, vae=vae), vae=vae, source_image=a, target_latent=lat,
                       fit_mode="fit")
            if b is not None:
                pat.update(source_latent_b=g.add("VAEEncode", pixels=b, vae=vae), source_image_b=b,
                           ref_position_a="beside (right of target)" if it["kind"] == "t2i" else "aligned (trained)",
                           ref_position="beside (right of target)" if it["kind"] == "t2i" else "aligned (trained)",
                           ref_boost=2.0 if use_id else 1.0, ref_boost_a=1.0 if use_id else 4.0)
            else:
                pat.update(ref_boost=2.0 if use_id else 4.0,
                           ref_position="beside (right of target)" if it["kind"] == "t2i" else "aligned (trained)")
            model = g.add("Krea2EditModelPatch", **pat)
        neg = g.add("ConditioningZeroOut", conditioning=pos)
        out = g.add("KSampler", model=model, seed=seed, steps=m["steps"], cfg=1.0, sampler_name="euler", scheduler="simple",
                    positive=pos, negative=neg, latent_image=lat, denoise=1.0)
    elif fam == "refine":
        clip = g.add("CLIPLoader", clip_name=m["clip"], type="flux2", device="default")
        src = g.add("ImageScale", image=g.add("LoadImage", image=names[0]), upscale_method="lanczos", width=W, height=H, crop="disabled")
        lat = g.add("VAEEncode", pixels=src, vae=vae)
        pos = g.add("ReferenceLatent", conditioning=g.add("CLIPTextEncode", clip=clip, text=prompt), latent=lat)
        neg = g.add("ReferenceLatent", conditioning=g.add("CLIPTextEncode", clip=clip, text=""), latent=lat)
        work = lat
        if m.get("mask") and len(names) > 1:          # 掩码：白 = 可重绘（脸以外），黑 = 保护（脸，按第一段的人脸框扩 1.35 倍、羽化）
            msk = g.add("ImageToMask", image=g.add("ImageScale", image=g.add("LoadImage", image=names[1]), upscale_method="bilinear",
                                                   width=W, height=H, crop="disabled"), channel="red")
            work = g.add("SetLatentNoiseMask", samples=lat, mask=msk)
        sig = g.add("SplitSigmasDenoise", sigmas=g.add("Flux2Scheduler", steps=m["steps"], width=W, height=H), denoise=m["denoise"])
        out = g.add("SamplerCustomAdvanced", noise=g.add("RandomNoise", noise_seed=seed),
                    guider=g.add("CFGGuider", model=model, positive=pos, negative=neg, cfg=1.0),
                    sampler=g.add("KSamplerSelect", sampler_name="euler"), sigmas=[sig[0], 1], latent_image=work)
    elif fam == "klein":
        clip = g.add("CLIPLoader", clip_name=m["clip"], type="flux2", device="default")
        pos = g.add("CLIPTextEncode", clip=clip, text=prompt)
        neg = g.add("CLIPTextEncode", clip=clip, text="" if m["cfg"] <= 1 else NEG)
        for n in names:
            lt = g.add("VAEEncode", pixels=load_img(g, n, 1.0), vae=vae)
            pos = g.add("ReferenceLatent", conditioning=pos, latent=lt)
            neg = g.add("ReferenceLatent", conditioning=neg, latent=lt)
        guider = g.add("CFGGuider", model=model, positive=pos, negative=neg, cfg=m["cfg"])
        out = g.add("SamplerCustomAdvanced", noise=g.add("RandomNoise", noise_seed=seed), guider=guider,
                    sampler=g.add("KSamplerSelect", sampler_name="euler"), sigmas=g.add("Flux2Scheduler", steps=m["steps"], width=W, height=H),
                    latent_image=g.add("EmptyFlux2LatentImage", width=W, height=H, batch_size=1))
    else:
        raise ValueError(fam)
    dec = g.add("VAEDecode", samples=out, vae=vae)
    g.add("SaveImage", images=dec, filename_prefix=prefix)
    return dict(g)


def r2_inputs(it, m):
    """第 2 轮输入：第一段首帧复制进 ComfyUI input；掩码按 results.json 里第一段的人脸框生成（白 = 可重绘，黑 = 脸）"""
    from PIL import Image, ImageDraw, ImageFilter
    inp = Path(COMFY_IN) / "bakeoff"
    src = HERE / "out" / f"{it['stage1']}.png"
    a = f"r2src__{it['stage1']}.png"
    if not (inp / a).exists():
        shutil.copy(src, inp / a)
    names = ["bakeoff/" + a]
    if m.get("mask"):
        res = json.loads((HERE / "results.json").read_text(encoding="utf-8"))["items"].get(it["stage1"], {})
        faces = (res.get("remote") or {}).get("faces") or []
        im = Image.open(src)
        mk = Image.new("L", im.size, 255)
        d = ImageDraw.Draw(mk)
        for f in faces:
            x1, y1, x2, y2 = f["bbox"]
            cx, cy, w, h = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) * 1.35, (y2 - y1) * 1.35
            d.ellipse((cx - w / 2, cy - h / 2 - h * 0.08, cx + w / 2, cy + h / 2), fill=0)
        mk = mk.filter(ImageFilter.GaussianBlur(max(4, im.size[0] // 96)))
        b = f"r2mask__{it['stage1']}.png"
        Image.merge("RGB", (mk, mk, mk)).save(inp / b)
        names.append("bakeoff/" + b)
    return names


CONTROL_FAILS = {"I2", "I3", "I4", "I5", "I9"}   # text / face 对照组刻意缺资产


def submittable(it, plan):
    """契约 §0.1：preflight 不过不提交。例外只有对照组（text / face）刻意缺资产这几项；I8（LoRA 白名单）任何组都不放行。
    编辑组与空镜不走首帧 preflight，但模型挂的 LoRA 必须在白名单（plan["lora_allow"]）。"""
    allow = set(plan.get("lora_allow") or [])
    m = plan["models"][it["model"]]
    if any(x[0] not in allow for x in m.get("loras") or []):
        return False
    if m["fam"] == "krea2id" and not ({m["lora_id"], m["lora_gen"]} <= allow):
        return False
    pf = it.get("preflight")
    if not pf:
        return True
    if pf.get("ok"):
        return True
    fails = {x["id"] for x in pf.get("fail", [])}
    return it["mode"] in ("text", "face") and fails <= CONTROL_FAILS


def api(url, path, data=None, timeout=60):
    req = urllib.request.Request(url + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def _ns_tag(it: dict, idx: int, total: int) -> dict:
    """GPU 面板标签：模型对比 BAKEOFF 第 idx/total 张；服务器平铺目录里没有 comfy_tag.py 时用同格式的普通 dict"""
    obj = " ".join(str(x) for x in (it.get("model"), it.get("mode")) if x)
    f = {"idx": idx, "total": total, "obj": obj or None, "label": it.get("kind") or None, "job": it.get("id")}
    try:
        sp = str(ROOT / "services" / "agent")
        if sp not in sys.path:
            sys.path.append(sp)
        from ns_agent import comfy_tag as CT
        return CT.make("BAKEOFF", "bakeoff", **f)
    except Exception:  # noqa: BLE001
        return {"agent": "BAKEOFF", "kind": "bakeoff", "v": 1, "t": round(time.time(), 1),
                **{k: v for k, v in f.items() if v not in (None, "")}}


def gen(argv):
    from PIL import Image
    lanes = [a for a in argv if a.startswith("--lanes=")]
    ports = (lanes[0].split("=", 1)[1] if lanes else "8188,8189").split(",")   # gpu36:2 归 VIDEO10（总调度 10-31）
    smoke = any(a == "--smoke" for a in argv)
    seed0 = any(a == "--seed0" for a in argv)                # GPU 紧张时只出第 1 个 seed
    modes_f = [a.split("=", 1)[1].split(",") for a in argv if a.startswith("--modes=")]
    kind_first = any(a == "--edit-first" for a in argv)          # 每个模型×组只出 1 张，先验证图能跑
    only = [a.split("=", 1)[1].split(",") for a in argv if a.startswith("--models=")]
    kinds = [a.split("=", 1)[1].split(",") for a in argv if a.startswith("--kinds=")]
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    models = plan["models"]
    outd = HERE / "out"
    outd.mkdir(exist_ok=True)
    inp = Path(COMFY_IN) / "bakeoff"
    inp.mkdir(parents=True, exist_ok=True)
    for f in plan["files"]:                          # 参考图放进 ComfyUI input/bakeoff/（同机，不经上传）
        dst = inp / f.replace("/", "__")
        if not dst.exists() and (HERE / "refs" / f).exists():
            shutil.copy(HERE / "refs" / f, dst)
    avail = set()
    for p in ports:
        oi = api(f"http://127.0.0.1:{p}", "/object_info/UNETLoader")
        avail |= set(oi["UNETLoader"]["input"]["required"]["unet_name"][0])
    todo = {}
    n_done0 = 0
    for it in plan["items"]:
        if only and it["model"] not in only[0] or kinds and it["kind"] not in kinds[0]:
            continue
        if it["kind"] == "prod":
            continue
        if (outd / f"{it['id']}.png").exists():
            n_done0 += 1                                # GPU 面板进度（第 idx/total 张）算上已出完的
            continue
        if any(not (inp / r.replace("/", "__")).exists() for r in it["refs"]):
            continue
        if it.get("stage1") and not (outd / f"{it['stage1']}.png").exists():
            continue
        if models[it["model"]]["unet"] not in avail or not submittable(it, plan):
            continue
        if seed0 and it["seed"] not in (SEEDS[0], None):
            continue
        if modes_f and it["mode"] not in modes_f[0]:
            continue
        if smoke and any(x["model"] == it["model"] and x["mode"] == it["mode"] for x in todo.get(it["model"], [])):
            continue
        sr = (0 if it["seed"] in (SEEDS[0], None) else 2) + (0 if (kind_first and it["kind"] == "edit") else 1 if kind_first else 0)           # 先把所有模型的第 1 个 seed 出完（GPU 让道时也有完整的一轮可比）
        todo.setdefault((sr, it["model"]), []).append(it)
    order = sorted(todo, key=lambda k: (k[0], PRIORITY.index(k[1]) if k[1] in PRIORITY else 99))
    log(f"GEN 待出 {sum(map(len, todo.values()))} 张，模型 {order}，道 {ports}")
    lock = threading.Lock()
    res_p = HERE / "gen_meta.jsonl"
    prog = {"n": n_done0, "total": n_done0 + sum(map(len, todo.values()))}

    def worker(port):
        url = f"http://127.0.0.1:{port}"
        gpu = int(port) - 8188
        while True:
            with lock:
                if not order:
                    return
                mk = order.pop(0)
                its = todo.pop(mk)
            m = models[mk[1]]
            for it in its:
                wait_yield(url, port)                  # 让道模式：hold 文件 + 本道空闲满 3 分钟才交（总调度 11-01，BAKEOFF 优先级最低）
                names = ["bakeoff/" + r.replace("/", "__") for r in it["refs"]]
                if it.get("stage1"):
                    names = r2_inputs(it, m)
                prefix = f"bakeoff/{it['id']}"
                t0 = time.monotonic()
                try:
                    body = {"prompt": build(it, m, names, prefix), "client_id": "bakeoff-" + uuid.uuid4().hex[:8]}
                    with lock:
                        prog["n"] += 1
                        idx = prog["n"]
                    try:   # GPU 任务归属标签（K-OPS-G01，extra_data.ns_tag）；出错就不带标签
                        body["extra_data"] = {"ns_tag": _ns_tag(it, idx, prog["total"])}
                    except Exception:  # noqa: BLE001
                        body.pop("extra_data", None)
                    pid = api(url, "/prompt", body)["prompt_id"]
                    while True:
                        time.sleep(2)
                        h = api(url, f"/history/{pid}")
                        if pid in h and h[pid].get("status", {}).get("completed") is not None or pid in h and h[pid].get("outputs"):
                            break
                    ent = h[pid]
                    st = ent.get("status", {})
                    if st.get("status_str") == "error":
                        msg = [x for x in st.get("messages", []) if x[0] == "execution_error"]
                        raise RuntimeError(str(msg)[:600])
                    img = next(i for o in ent["outputs"].values() for i in o.get("images", []))
                    src = Path(COMFY_OUT) / f"gpu{gpu}" / img.get("subfolder", "") / img["filename"]
                    im = Image.open(src).convert("RGB")
                    raw = im.size
                    if im.size != (PW, PH):
                        im = im.resize((PW, PH), Image.LANCZOS)
                    im.save(outd / f"{it['id']}.png")
                    rec = dict(id=it["id"], ok=True, sec=round(time.monotonic() - t0, 1), raw=raw, raw_path=str(src), lane=port)
                except Exception as e:  # noqa: BLE001
                    rec = dict(id=it["id"], ok=False, err=str(e)[:600], sec=round(time.monotonic() - t0, 1), lane=port)
                with lock:
                    with open(res_p, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                log(port, it["id"], "OK" if rec["ok"] else "ERR " + rec.get("err", "")[:200], rec["sec"])
                if not rec["ok"] and "error" in rec.get("err", "").lower() and its.index(it) == 0:
                    log(port, mk, "第一张就报错，跳过该模型其余作业")
                    break

    ths = [threading.Thread(target=worker, args=(p,)) for p in ports]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    log("GEN 完成")


YIELD_IDLE_S = 180


def wait_yield(url, port):
    """让道模式（总调度 11-01）：① run/hold 列出本道端口 → 不交；② 本道 ComfyUI 有别人的任务（运行或排队）→ 不交，
    且要等别人的最后一个任务结束后空闲满 YIELD_IDLE_S 秒才交；只有自己的任务刚结束则不用等。每次只交 1 个。"""
    last_foreign = 0.0
    while True:
        if port in hold_ports():
            time.sleep(20)
            continue
        try:
            q = api(url, "/queue")
            ents = (q.get("queue_running") or []) + (q.get("queue_pending") or [])
        except Exception:  # noqa: BLE001
            time.sleep(20)
            continue
        if ents:
            if any(not str((e[3] or {}).get("client_id", "") if len(e) > 3 and isinstance(e[3], dict) else "").startswith("bakeoff-")
                   for e in ents):
                last_foreign = time.time()
            time.sleep(15)
            continue
        if last_foreign == 0.0:
            try:                                   # 最近一条历史是别人的 → 从它结束时起算空闲
                h = api(url, "/history?max_items=1")
                for v in h.values():
                    cid = str((v.get("prompt") or [None] * 4)[3].get("client_id", "")) if len(v.get("prompt") or []) > 3 else ""
                    msgs = (v.get("status") or {}).get("messages") or []
                    ts = max([m[1].get("timestamp", 0) for m in msgs if isinstance(m, list) and len(m) > 1 and isinstance(m[1], dict)] or [0])
                    if not cid.startswith("bakeoff-") and ts:
                        last_foreign = ts / 1000.0
            except Exception:  # noqa: BLE001
                pass
        if time.time() - last_foreign >= YIELD_IDLE_S:
            return
        time.sleep(15)


def hold_ports():
    try:
        return set((HERE / "run/hold").read_text().split())
    except OSError:
        return set()


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(map(str, a))
    print(line, flush=True)
    with open(HERE / "bakeoff.log" if ON_SERVER else AB / "bakeoff.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ssh(cmd, timeout=600):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, cmd], capture_output=True, timeout=timeout)
    return (r.stdout + r.stderr).decode(errors="replace")


def start(argv):
    args = " ".join(argv)
    print(ssh(f"cd {SRV} || exit 1; mkdir -p run; if [ -f run/gen.pid ] && kill -0 $(cat run/gen.pid) 2>/dev/null; then echo ALREADY; exit 0; fi; "
              f"(PYTHONUTF8=1 /root/work/fredw/venv/bin/python -u run.py gen {args}; PYTHONUTF8=1 /root/work/fredw/venv_idm/bin/python -u score_srv.py) "
              f">> run/gen.out 2>&1 < /dev/null & echo $! > run/gen.pid; echo STARTED $(cat run/gen.pid)"))


def pull():
    d = AB / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    blob = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, f"cd {SRV} && tar czf - results.json gen_meta.jsonl thumbs full 2>/dev/null"],
                          capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(blob)) as t:
        t.extractall(AB, filter="data")
    print("pulled", len(blob) / 1e6, "MB", len(list(d.glob("*.jpg"))), "thumbs")


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "prep":
        prep()
    elif cmd == "push":
        push()
    elif cmd == "gen":
        gen(argv[1:])
    elif cmd == "start":
        start(argv[1:])
    elif cmd == "status":
        print(ssh(f"cd {SRV}; tail -5 bakeoff.log; wc -l gen_meta.jsonl; ls out | wc -l"))
    elif cmd == "pull":
        pull()
    elif cmd == "page":
        import page
        page.build()
    else:
        print(__doc__)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(HERE))
    main(sys.argv[1:])
