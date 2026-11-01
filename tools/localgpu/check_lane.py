"""LOCALGPU（11-01，总调度 fredw-2b 派）：本机出图道 laptop:0 的自动核对（knowledge K-OPS-L01）。

规则：本机道只是“另一台出图机器”，出图参数一项都不能和 leica_sstar（项目方确认的徕卡 S★）不同——
  ① 道记录（config/render_endpoints.json lanes.laptop:*）只许地址 / 调度字段，不许带任何出图参数；
  ② 生产预设（frame_redo_preset，现为 frame_v9）解析出的出图参数与 leica_sstar 逐项相同（frame_v9 只多了参考图结构说明）；
  ③ 道上 ComfyUI 有这套参数要用到的全部节点和模型文件，版本与服务器相同（0.42.0）；
  ④（--sha）模型文件 sha256 与 HF 官方 / 服务器记录一致（EXPECTED_SHA256）。
用法：python tools/localgpu/check_lane.py [--live] [--sha]   → 打印 JSON，不通过退出码 1
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/render_router", "services/agent", "packages/schema", "services/api"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

REF_PRESET = "leica_sstar"
COMFY_VERSION = "0.42.0"            # 服务器 ComfyUI 版本（CHANGELOG fredw-92/F1“ComfyUI 0.42”；本机 D:\ns_comfy 同 tag v0.42.0）
LANE_KEYS = {"url", "label", "image_only", "concurrency", "hold", "preset_lock", "disabled", "_comment",
             "yield_url", "yield_timeout_s"}       # yield_url：同卡轮流的看图服务（交图前请它卸载），调度字段，不影响出图参数
# 预设里与出图结果有关的字段（style_suffix 在 unified 路径被置空不重复接，但两边必须一样，照比）
GEN_KEYS = ("unet", "sampler", "vae", "width", "height", "spec_words", "loras", "render_scale", "sharpen", "style_suffix",
            "steps", "cfg", "scheduler", "shift", "two_stage", "detail_pass", "strength", "grade_strength")
NODES = ("UNETLoader", "CLIPLoader", "VAELoader", "LoraLoaderModelOnly", "QwenImage21Cache", "TextEncodeQwenImage21",
         "ManualSigmas", "SamplerCustomAdvanced", "CFGGuider", "RandomNoise", "KSamplerSelect", "EmptyLatentImage",
         "LoadImage", "SaveImage", "VAEDecode")
# sha256：HF Comfy-Org/Qwen-Image-2.1 与 madebyollin/texture-fix-vae-for-qwen-image-2.1 的 LFS oid（11-01 实查）；
# krea2 = 服务器记录前缀 b94be18f（CHANGELOG 传输记录）+ 本机全量；Pika = 官方 comfy/SHA256SUMS
EXPECTED_SHA256 = {
    "diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors": "8144a0182964aa8403ad6dbc011db837304167d235161b9aabaa8532e967314c",
    "text_encoders/qwen3vl_8b_int8_convrot.safetensors": "8bfd0f6e12abf2d2d697ecc888e5e90b0d6741d6708f05799f53afa560452e8f",
    "vae/texture_fix_vae_for_qwen_image_2.1_bf16.safetensors": "36f56608b02077a50a08ea3dbcdb88351298ceba49948f41f9f87186378e6908",
    "vae/qwen_image_2.1_vae_bf16.safetensors": "bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9",
    "loras/krea2_film_texture_qwen21.safetensors": "b94be18fa55f8389bd65236690fe03f8609b006e2cc428bfda7235836b94ded8",
}
OPTIONAL_SHA256 = {
    "loras/pika_h3_flex_fl2va_comfy_bf16.safetensors": "68783e6447696ec365d13c0554941e070bee4cfea13c37da52498ec4f9a53f89",
}
MODELS_DIR = Path(r"D:\ns_comfy\models")


def local_lanes(cfg: dict) -> dict:
    return {k: v for k, v in (cfg.get("lanes") or {}).items() if str(k).startswith("laptop:")}


def gen_params(preset: str) -> dict:
    """预设经 image_params.resolve（与 unified_frame.build_graph 同一调用：style_suffix 不覆盖，比的是预设本身）"""
    from ns_render import image_params as IP
    eff = IP.resolve(preset, None)
    return {k: eff.get(k) for k in GEN_KEYS}


def required_files(preset: str) -> dict:
    """这套参数送进 ComfyUI 的模型文件名（与 build_graph → IP.apply 同一映射）"""
    from ns_render import image_params as IP
    from ns_render import workflows as W
    eff = IP.resolve(preset, None)
    return {"unet": IP.UNETS[eff["unet"]], "clip": W.QwenModel().clip, "vae": IP.VAES[eff["vae"]],
            "loras": [x["name"] for x in eff.get("loras") or []]}


def check_config(cfg_path: Path | None = None, rq_path: Path | None = None) -> list[str]:
    """离线核对（①②）：返回问题列表，空 = 通过"""
    cfg = json.loads((cfg_path or ROOT / "config/render_endpoints.json").read_text(encoding="utf-8"))
    rq = json.loads((rq_path or ROOT / "config/render_quality.json").read_text(encoding="utf-8"))
    errs = []
    lanes = local_lanes(cfg)
    if not lanes:
        errs.append("render_endpoints.json 没有 laptop:* 道")
    for k, v in lanes.items():
        if not isinstance(v, dict) or not v.get("image_only"):
            errs.append(f"{k} 必须 image_only=true（12 GB 笔记本不接视频）")
            continue
        extra = set(v) - LANE_KEYS
        if extra:
            errs.append(f"{k} 道记录带了出图参数 / 未知字段 {sorted(extra)}——本机道不许改参数，参数只来自 render_quality.json 预设")
        if v.get("preset_lock", REF_PRESET) != REF_PRESET:
            errs.append(f"{k} preset_lock={v.get('preset_lock')!r}，必须是 {REF_PRESET}")
        if int(v.get("concurrency") or 1) != 1:
            errs.append(f"{k} 并发必须 1（12 GB 显存，实测峰值 10.6–11.7 GB）")
    presets = {p["id"]: p for p in rq.get("image_presets") or []}
    prod = rq.get("frame_redo_preset") or "frame_v9"
    if REF_PRESET not in presets:
        errs.append(f"render_quality.json 没有 {REF_PRESET}")
        return errs
    a = {k: presets[REF_PRESET]["params"].get(k) for k in GEN_KEYS}
    b = {k: (presets.get(prod) or {}).get("params", {}).get(k) for k in GEN_KEYS}
    diff = {k: (a[k], b[k]) for k in GEN_KEYS if a[k] != b[k]}
    if diff:
        errs.append(f"生产预设 {prod} 与 {REF_PRESET} 出图参数不同：{diff}")
    return errs


def _get(url: str, path: str, timeout: float = 15):
    with urllib.request.urlopen(url.rstrip("/") + path, timeout=timeout) as r:
        return json.loads(r.read())


def check_live(url: str, preset: str = REF_PRESET) -> list[str]:
    """在线核对（③）：节点、模型文件、ComfyUI 版本"""
    errs = []
    try:
        st = _get(url, "/system_stats")
        oi = _get(url, "/object_info", 60)
    except Exception as e:  # noqa: BLE001
        return [f"{url} 连不上：{e!r}"[:200]]
    ver = (st.get("system") or {}).get("comfyui_version")
    if ver != COMFY_VERSION:
        errs.append(f"ComfyUI 版本 {ver} ≠ 服务器 {COMFY_VERSION}")
    missing = [n for n in NODES if n not in oi]
    if missing:
        errs.append(f"缺节点 {missing}")

    def opts(cls, key):
        try:
            return set(oi[cls]["input"]["required"][key][0])
        except (KeyError, IndexError, TypeError):
            return set()
    need = required_files(preset)
    for kind, cls, key in (("unet", "UNETLoader", "unet_name"), ("clip", "CLIPLoader", "clip_name"), ("vae", "VAELoader", "vae_name")):
        if need[kind] not in opts(cls, key):
            errs.append(f"缺模型 {need[kind]}（{cls}）")
    for name in need["loras"]:
        if name not in opts("LoraLoaderModelOnly", "lora_name"):
            errs.append(f"缺 LoRA {name}")
    return errs


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def check_sha(models: Path = MODELS_DIR) -> tuple[list[str], dict]:
    errs, got = [], {}
    for rel, exp in {**EXPECTED_SHA256, **OPTIONAL_SHA256}.items():
        p = models / rel
        if not p.exists():
            if rel in EXPECTED_SHA256:
                errs.append(f"缺文件 {p}")
            else:
                got[rel] = "未下完 / 未装（可选）"
            continue
        h = sha256(p)
        got[rel] = h
        if h != exp:
            errs.append(f"{rel} sha256 {h[:12]}… ≠ 期望 {exp[:12]}…")
    return errs, got


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    out: dict = {"config": check_config()}
    cfg = json.loads((ROOT / "config/render_endpoints.json").read_text(encoding="utf-8"))
    if "--live" in argv:
        out["live"] = {k: check_live(v["url"]) for k, v in local_lanes(cfg).items()}
    if "--sha" in argv:
        out["sha_errors"], out["sha"] = check_sha()
    out["params"] = gen_params(REF_PRESET)
    out["files"] = required_files(REF_PRESET)
    bad = bool(out["config"]) or any(out.get("live", {}).values()) or bool(out.get("sha_errors"))
    out["ok"] = not bad
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
