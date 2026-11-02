"""图像工坊后端（IMGLAB → FILMUI 接线；项目方 11-02 12:5x：图像工坊做进产品）。纯函数，不起服务：
FILMUI 在 ns_api 里挂两个路由，直接调用这里：

  GET  /api/image-workshop/bases            → list_bases()
  POST /api/image-workshop/jobs  {base, prompt, refs[], seed?, count=1, width?, height?, preset?}
                                            → build_jobs(...) 得到 ComfyUI 图（每张一个），交给现有出图道（ns_render.comfy_client）

就绪状态唯一来源：data/ab/imglab/bases_status.json（IMGLAB 冒烟 / A/B 后更新；没登记 = not_ready）。
基座 id：qwen21（现行 S★ R0，生产用）/ klein（FLUX 3 Image Klein，FLUX Kommunity License，非商用测试）/ moss（MOSS-Image SFT，Apache-2.0）。
预设：S★ R0（qwen21 默认）、各基座官方默认；“时尚大片”“写实”预设在项目方看图挑定后加进 PRESETS（现在只登记候选，不开放）。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "data/ab/imglab/bases_status.json"

BASES = {
    "qwen21": {"name": "Qwen-Image 2.1 Turbo（S★ R0，现行剧集观感）", "license": "Qwen Research License（非商用；上线前处理授权）",
               "max_refs": 10, "default_preset": "sstar_r0", "size": [768, 1344]},
    "klein": {"name": "FLUX 3 Image Klein", "license": "FLUX Kommunity License v1.0（非商用测试；年收入 < 500 万美元可商用出图）",
              "max_refs": 10, "default_preset": "klein_default", "size": [864, 1536]},
    "moss": {"name": "MOSS-Image SFT", "license": "Apache-2.0", "max_refs": 0, "default_preset": "moss_default", "size": [864, 1536],
             "note": "本体文生图：参考图只在 edit LoRA 预设里用（身份保持未验证）"},
}
PRESETS = {
    "sstar_r0": {"base": "qwen21", "label": "S★ R0（L-087，项目方定的剧集观感）", "params": {}},
    "klein_default": {"base": "klein", "label": "Klein 官方蒸馏档（16 步 cfg1 euler/simple，int8）", "params": {}},
    "moss_default": {"base": "moss", "label": "MOSS 官方模板档（25 步 cfg2.5 er_sde，SLG 22）", "params": {}},
}


def status() -> dict:
    try:
        return json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 没有状态文件 = 全部按未就绪（qwen21 除外，见 list_bases）
        return {}


def list_bases() -> list[dict]:
    st = status()
    out = []
    for bid, b in BASES.items():
        s = st.get(bid) or {}
        ready = "ready" if bid == "qwen21" else s.get("state", "not_ready")
        out.append({"id": bid, **b, "state": ready, "state_detail": s.get("detail") or ("生产在用" if bid == "qwen21" else "未登记"),
                    "presets": [{"id": k, "label": v["label"]} for k, v in PRESETS.items() if v["base"] == bid]})
    return out


def build_jobs(base: str, prompt: str, ref_names: list[str], seed: int | None = None, count: int = 1,
               width: int | None = None, height: int | None = None, preset: str | None = None, upload=None,
               prefix: str = "workshop/img") -> list[dict]:
    """→ [{"seed", "graph"}]。ref_names = 已上传到 ComfyUI 的参考图名（qwen21 需要 upload 回调与仓库相对路径，见下）。
    未就绪的基座直接报错（就绪一个开放一个）。"""
    b = next((x for x in list_bases() if x["id"] == base), None)
    if not b:
        raise KeyError(f"没有基座 {base}")
    if b["state"] != "ready":
        raise PermissionError(f"{b['name']} 还没就绪：{b['state_detail']}")
    pr = PRESETS.get(preset or b["default_preset"]) or {}
    if pr.get("base") not in (None, base):
        raise ValueError(f"预设 {preset} 不属于基座 {base}")
    seeds = [seed + i for i in range(count)] if seed is not None else [random.randint(1, 2**48) for _ in range(count)]
    w, h = width or b["size"][0], height or b["size"][1]
    jobs = []
    for s in seeds:
        if base == "qwen21":
            from ns_render import unified_frame as UF
            if upload is None:
                raise ValueError("qwen21 需要 upload 回调（参考图为仓库相对路径）")
            g, _eff, _sent = UF.build_graph({"prompt": prompt, "refs": list(ref_names)}, s, upload, f"{prefix}_s{s}")
        else:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            import bases as BS
            g = BS.build(base, prompt, list(ref_names)[: b["max_refs"]] if b["max_refs"] else [], s, f"{prefix}_s{s}",
                         {**(pr.get("params") or {}), "width": w, "height": h})
        jobs.append({"seed": s, "graph": g})
    return jobs
