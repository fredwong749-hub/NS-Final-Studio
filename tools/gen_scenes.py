"""
场景底板（plan P1，SOP_parameters S2「场景底板」）：每个 scene_id 一张空场 9:16 底板 assets/scenes/<scene_id>/plate.png，
镜头机位差异大时加 plate_low / plate_top。读 data/scenes.json（state_timeline 生成）+ 剧本 img 原文。

本工具**不出图**：只往 data/jobs/queue/ 写任务（gpu_grab 队列消费，格式同 data/jobs/gpu3_char_variety_20261030.json），
图回来后用 finalize 在本机做裁切 + 调色（CPU）并写清单。

    uv run python tools/gen_scenes.py list   [--draft]                      # 看任务与提示词
    uv run python tools/gen_scenes.py emit   [--only sk_x ...] [--force] [--draft] [--dry-run]
    uv run python tools/gen_scenes.py finalize [--only sk_x ...]            # <stem>_raw.png → <stem>.png（候选）
    uv run python tools/gen_scenes.py sheet

锁定配方（SOP_parameters S2 场景底板 + S3 图像）：
  Qwen-Image 2.1 Base 35 步 cfg 3.0、texture-fix VAE、krea2 0.5；第一遍 928×1632（≈1.5MP），lanczos 放大到 1152×2016，
  第二遍 denoise 0.30 → <stem>_raw.png；finalize：lanczos 居中裁切到 768×1344（H3 输入尺寸，首尾帧同法）→ <stem>_ungraded.png，
  再 Reinhard LAB 迁移到 assets/style/color_reference_01.png（强度 0.6，夜景/暗场 0.3）→ <stem>.png。
闸门：data/state_timeline.json `provisional: true`（S1 未过）时拒绝出任务；--draft 才放行，任务与清单都标 draft（不得用于 S3）。
清单 assets/scenes/<id>/manifest.json（docs/state_timeline.md §三）：finalize 写 plate / scene_id / light / built_from
{scenes_sha, scenes_json_sha256, bible_version} / plate_status=candidate；**确认只由项目方** `tools/sop_owner.py plate <id> "原话"`，
本工具从不写确认字段（重出新图时清掉旧确认）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import tomllib
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(os.environ.get("NS_PROJECT_ROOT") or Path(__file__).resolve().parent.parent)
REPO = Path(__file__).resolve().parent.parent
QUEUE = REPO / "data" / "jobs" / "queue"

MODEL = "qwen_image_2.1_int8_convrot.safetensors"
VAE = "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors"
LORAS = [["krea2_film_texture_qwen21.safetensors", 0.5]]
STEPS, CFG = 35, 3.0
FIRST_PASS = (928, 1632)
SECOND_PASS = (1152, 2016)
SECOND_DENOISE = 0.30
SECOND_STEPS = 12
CROP = (768, 1344)
COLOR_REF = "assets/style/color_reference_01.png"
STRENGTH, STRENGTH_DARK = 0.6, 0.3
DARK_TIMES = {"night"}

LIGHT_RE = re.compile(r"[^，,。；;：:（）()]*(?:灯|光|霓虹|烛|窗|阳光|月光|晨光|夕阳|晚霞|夜景|射灯|台灯|吊灯|路灯)[^，,。；;：:（）()]*")
PEOPLE_RE = re.compile(r"(她|他|女性|男性|男人|女人|林晚|顾沉|陈宇|Alex|Kai|Leo|Ryan|人群|同事|穿孔师|纹身师|柜姐|两人|双人|蓝发)")
ANGLES = {"low": ("低机位|仰拍|仰视", "低机位仰拍的视角，镜头贴近地面向上看"),
          "top": ("俯拍|鸟瞰|顶拍|俯视", "高机位俯拍的视角，从上往下看")}
NEG = "人物、人影、人体、脸、手、文字、字幕、水印、标志、低清、变形、灰暗脏乱的色调"
TRIGGER_RE = re.compile(r"(?<![A-Za-z0-9_])[a-z][a-z0-9_]{3,}(?![A-Za-z0-9_])")   # LoRA 触发词（全小写 ASCII 词）不进底板提示词
TOD_ZH = {"morning": "清晨", "day": "白天", "dusk": "黄昏", "night": "夜晚"}
OWNER_KEYS = ("owner_confirmed_at", "owner_confirmed_ref", "plate_sha256")


class GateError(SystemExit):
    pass


# ------------------------------------------------------------------ 读取

def _read(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def sha_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def _state(root: Path, name: str) -> Path:
    """V2CUT-O 11-03：状态表 / 场景表按当前剧取（V1 = data/，其它剧 = data/import/runs/<run>/），不回退 V1 全局文件"""
    from ns_agent import run_paths as RP
    return RP.state_dir(root) / name


def timeline_provisional(root: Path) -> bool:
    """S1 闸门：state_timeline.json 缺失或 provisional 都当作未通过"""
    t = _read(_state(root, "state_timeline.json"), None)
    return not isinstance(t, dict) or bool(t.get("provisional", True))


def load_scenes_doc(root: Path) -> dict:
    d = _read(_state(root, "scenes.json"), None)
    if d is None:
        raise SystemExit(f"没有 {_state(root, 'scenes.json')}：先跑 tools/build_state_timeline.py")
    return d if isinstance(d, dict) else {"scenes": d}


def colour_strengths(root: Path) -> tuple[float, float]:
    try:
        vb = tomllib.loads((root / "config" / "visual_bible.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return STRENGTH, STRENGTH_DARK

    def find(d, k):
        if isinstance(d, dict):
            if k in d:
                return d[k]
            for v in d.values():
                r = find(v, k)
                if r is not None:
                    return r
        return None
    return (float(find(vb, "color_match_strength") or STRENGTH), float(find(vb, "color_match_dark_shots") or STRENGTH_DARK))


def shot_texts(root: Path) -> tuple[dict[str, str], str]:
    d = _read(root / "data" / "import" / "script_v2.json", None) or {"episodes": [], "globals": {}}
    out = {}
    for ep in d.get("episodes", []):
        for s in ep.get("shots", []):
            t = s.get("img_prompt") or ""
            for key in (f"ep{ep['number']:02d}-S{s['index']}", f"{ep['number']}-{s['index']}", f"ep{ep['number']}-S{s['index']}"):
                out[key] = t
    return out, (d.get("globals") or {}).get("image_suffix", "")


def shot_key(sh) -> str:
    if isinstance(sh, dict):
        if "shot_id" in sh:
            return sh["shot_id"]
        if "episode" in sh and "index" in sh:
            return f"ep{int(sh['episode']):02d}-S{sh['index']}"
    return str(sh)


def strip_people(text: str) -> str:
    """去掉写到人物的分句和 LoRA 触发词（触发词会把道具“穿上”或画出人物）"""
    parts = (TRIGGER_RE.sub("", p).strip(" ；;") for p in re.split(r"[，,]", text) if not PEOPLE_RE.search(p))
    return "，".join(p for p in parts if p)


def scene_light(sc: dict) -> dict:
    light = (sc.get("plate_detail") or {}).get("light")
    if isinstance(light, dict):
        return light
    return {"time": sc.get("time_of_day") or None, "key_direction": None, "colour_temp": None}


# ------------------------------------------------------------------ 任务

def _seed(scene_id: str, stem: str, scenes_sha: str) -> int:
    return int(hashlib.sha256(f"plate|{scene_id}|{stem}|{scenes_sha}".encode()).hexdigest()[:12], 16)


def scene_jobs(root: Path = ROOT, draft: bool = False) -> tuple[dict, list[dict]]:
    """→ (队列文件头, 任务列表)。不检查闸门（emit 检查）。"""
    doc = load_scenes_doc(root)
    texts, suffix = shot_texts(root)
    scenes_sha = doc.get("scenes_sha") or ""
    scenes_file_sha = sha_file(_state(root, "scenes.json"))
    built_from = {"scenes_sha": scenes_sha, "scenes_json_sha256": scenes_file_sha,
                  "bible_version": doc.get("bible_version"), "provisional": bool(doc.get("provisional", True)),
                  "draft": draft}
    s_norm, s_dark = colour_strengths(root)
    ref_sha = sha_file(root / COLOR_REF)
    jobs = []
    for sc in doc.get("scenes", []):
        sid = sc["scene_id"]
        place, tod_key = sc.get("place", ""), sc.get("time_of_day", "")
        tod = TOD_ZH.get(tod_key, tod_key)
        light = scene_light(sc)
        shots = [texts.get(shot_key(s), "") for s in sc.get("shots", [])]
        lights = []
        for t in shots:
            for m in LIGHT_RE.findall(strip_people(t)):
                m = m.strip()
                if m and len(m) <= 30 and m not in lights:
                    lights.append(m)
        light_txt = "；光源与光线：" + "，".join(lights[:5]) if lights else ""
        env = [strip_people(t) for t in shots if t][:2]
        base = (f"电影场景空镜底板（空场，画面中没有任何人物）：{place}{'，' + tod if tod else ''}{light_txt}。"
                + (f"环境细节参考：{'；'.join(e for e in env if e)}。" if any(env) else "") +
                f"竖构图 9:16，视平线机位，干净整洁、陈设真实可信，空间纵深清楚。{suffix}。画面中绝对没有人、人影和文字")
        dark = (light.get("time") or tod_key) in DARK_TIMES
        variants = [("plate", base)]
        joined = "".join(shots)
        for ang, (kw, desc) in ANGLES.items():
            if re.search(kw, joined):
                variants.append((f"plate_{ang}", base.replace("视平线机位", desc)))
        for stem, prompt in variants:
            jobs.append({
                "id": f"scene_{sid}_{stem}", "kind": "scene_plate", "mode": "t2i",
                "model": MODEL, "steps": STEPS, "cfg": CFG, "size": list(FIRST_PASS), "lora": [list(x) for x in LORAS],
                "vae": VAE,
                "refine": {"upscale_to": list(SECOND_PASS), "upscale_method": "lanczos",
                           "scale": round(SECOND_PASS[1] / FIRST_PASS[1], 4), "steps": SECOND_STEPS,
                           "denoise": SECOND_DENOISE},
                "negative": NEG, "prompt": prompt, "seed": _seed(sid, stem, scenes_sha),
                "scene_id": sid, "stem": stem, "light": light, "built_from": built_from,
                "file": f"{stem}_raw.png", "out_dir": f"assets/scenes/{sid}/",
                "post": {"center_crop": list(CROP), "resample": "lanczos", "ungraded": f"{stem}_ungraded.png",
                         "color_match": {"method": "reinhard_lab", "reference": COLOR_REF, "reference_sha256": ref_sha,
                                         "strength": s_dark if dark else s_norm, "dark": dark},
                         "final": f"{stem}.png", "where": "laptop: tools/gen_scenes.py finalize (CPU)"},
                "preset": "SOP_PLATE", "qc": "no people / no text (VL check); QC v3",
                "status": ("draft (S1 not passed; not for S3)" if draft else
                           "candidate (owner confirms via tools/sop_owner.py plate)"),
            })
    head = {"requested_by": "fredw-d9", "kind": "scene_plates",
            "purpose": "SOP-locked scene plates (empty set, no people/text) for S3 first/last frames",
            "gpu": "gpu3 idle GPU (never GPU2)", "scenes_sha": scenes_sha, "scenes_json_sha256": scenes_file_sha,
            "provisional": built_from["provisional"], "draft": draft,
            "confirmation": "owner only: uv run python tools/sop_owner.py plate <scene_id> \"原话\"",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    return head, jobs


def emit(root: Path = ROOT, *, only: list[str] | None = None, force: bool = False, draft: bool = False,
         dry_run: bool = False, queue_dir: Path = QUEUE) -> dict:
    if timeline_provisional(root) and not draft:
        raise GateError("data/state_timeline.json 仍是 provisional（S1 闸门未过）：不出场景底板任务。"
                        "要先看草稿用 --draft（不得用于 S3）")
    head, jobs = scene_jobs(root, draft=draft)
    picked, skipped = [], []
    for j in jobs:
        if only and j["scene_id"] not in only:
            continue
        if (root / j["out_dir"] / j["post"]["final"]).exists() and not force:
            skipped.append(j["id"])
            continue
        picked.append(j)
    name = f"scene_plates_{head['scenes_sha'] or 'nosha'}{'_draft' if draft else ''}.json"
    path = queue_dir / name
    if not picked:
        return {"status": "nothing", "path": None, "jobs": 0, "skipped": skipped}
    if path.exists() and not force:
        return {"status": "exists", "path": path.as_posix(), "jobs": 0, "skipped": skipped}
    if dry_run:
        return {"status": "dry_run", "path": path.as_posix(), "jobs": len(picked), "skipped": skipped,
                "doc": {**head, "jobs": picked}}
    _write(path, {**head, "jobs": picked})
    for j in picked:      # 清单只记“已排队”，不动 built_from / 确认字段（那些描述的是现有的图）
        mp = root / j["out_dir"] / "manifest.json"
        man = _read(mp, {}) or {}
        man.setdefault("plate", "plate.png")
        man["scene_id"] = j["scene_id"]
        man.setdefault("queued", {})[j["stem"]] = {"queue_file": path.name, "job_id": j["id"], "seed": j["seed"],
                                                   "light": j["light"], "built_from": j["built_from"],
                                                   "post": j["post"], "at": head["created_at"]}
        _write(mp, man)
    return {"status": "queued", "path": path.as_posix(), "jobs": len(picked), "skipped": skipped}


# ------------------------------------------------------------------ 本机后处理（CPU）

def center_crop(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """等比缩放到刚好覆盖目标（lanczos），再居中裁切——首帧与尾帧同法（P-B2）"""
    w, h = size
    s = max(w / img.width, h / img.height)
    nw, nh = max(w, round(img.width * s)), max(h, round(img.height * s))
    img = img.convert("RGB").resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _to_lab(rgb: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def _to_rgb(lab: np.ndarray) -> np.ndarray:
    import cv2
    return np.clip(cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_LAB2RGB) * 255.0 + 0.5, 0, 255).astype(np.uint8)


def reinhard(img: Image.Image, ref: Image.Image, strength: float) -> Image.Image:
    """Reinhard 2001：LAB 各通道均值/标准差迁移到参考图，按 strength 与原图混合"""
    src = _to_lab(np.asarray(img.convert("RGB")))
    r = ref.convert("RGB")
    r.thumbnail((768, 768))
    rl = _to_lab(np.asarray(r)).reshape(-1, 3)
    mu_s, sd_s = src.reshape(-1, 3).mean(0), src.reshape(-1, 3).std(0)
    mu_r, sd_r = rl.mean(0), rl.std(0)
    out = (src - mu_s) / np.maximum(sd_s, 1e-3) * sd_r + mu_r
    out = src + float(strength) * (out - src)
    out[..., 0] = np.clip(out[..., 0], 0, 100)
    return Image.fromarray(_to_rgb(out))


def finalize(root: Path = ROOT, *, only: list[str] | None = None) -> list[dict]:
    """图回来后：<stem>_raw.png → 裁切 <stem>_ungraded.png → 调色 <stem>.png；清单写 candidate（从不写确认）"""
    ref_path = root / COLOR_REF
    done = []
    for mp in sorted((root / "assets" / "scenes").glob("*/manifest.json")):
        man = _read(mp, {}) or {}
        sid = man.get("scene_id") or mp.parent.name
        if only and sid not in only:
            continue
        for stem, q in list((man.get("queued") or {}).items()):
            raw = mp.parent / f"{stem}_raw.png"
            if not raw.is_file():
                continue
            if not ref_path.is_file():
                raise SystemExit(f"缺调色参考图 {ref_path}")
            post = q["post"]
            img = center_crop(Image.open(raw), tuple(post["center_crop"]))
            img.save(mp.parent / post["ungraded"])
            cm = post["color_match"]
            graded = reinhard(img, Image.open(ref_path), cm["strength"])
            final = mp.parent / post["final"]
            graded.save(final)
            status = "draft" if q["built_from"].get("draft") else "candidate"
            rec = {"file": final.name, "seed": q["seed"], "light": q["light"], "built_from": q["built_from"],
                   "raw": raw.name, "ungraded": post["ungraded"],
                   "color_match": {**cm, "reference_sha256": sha_file(ref_path)},
                   "candidate_sha256": sha_file(final), "finalized_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "plate_status": status}
            if stem == "plate":
                for k in OWNER_KEYS:          # 新图 → 旧确认作废，须项目方重新确认
                    man.pop(k, None)
                man.update(plate=final.name, scene_id=sid, light=q["light"], built_from=q["built_from"],
                           plate_status=status, candidate_sha256=rec["candidate_sha256"])
            man.setdefault("variants", {})[stem] = rec
            man["queued"].pop(stem)
            done.append({"scene_id": sid, "stem": stem, "status": status,
                         "file": final.relative_to(root).as_posix()})
        if not man.get("queued"):
            man.pop("queued", None)
        _write(mp, man)
    return done


# ------------------------------------------------------------------ CLI

def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--draft", action="store_true")
    e = sub.add_parser("emit")
    e.add_argument("--only", nargs="*", default=[])
    e.add_argument("--force", action="store_true")
    e.add_argument("--draft", action="store_true", help="S1 未过也出（任务/清单标 draft，不得用于 S3）")
    e.add_argument("--dry-run", action="store_true")
    f = sub.add_parser("finalize")
    f.add_argument("--only", nargs="*", default=[])
    sub.add_parser("sheet")
    a = ap.parse_args(argv)
    if a.cmd == "sheet":
        sys.path.insert(0, str(Path(__file__).parent))
        import gen_assets as G  # noqa: PLC0415 （带 ns_render 依赖，只在出拼图时导入）
        files = sorted((ROOT / "assets" / "scenes").glob("*/plate*.png"))
        files = [p for p in files if not p.stem.endswith(("_raw", "_ungraded"))]
        print(G.sheet(None, G.SHEETS / "scenes.jpg", files, cols=6, cell=260,
                      title=f"scene plates ({len(files)})") if files else "no plates")
        return 0
    if a.cmd == "list":
        if timeline_provisional(ROOT):
            print("注意：state_timeline 仍是 provisional（S1 未过）；emit 需 --draft")
        _, jobs = scene_jobs(ROOT, draft=a.draft)
        for j in jobs:
            print(j["id"], "| strength", j["post"]["color_match"]["strength"], "|", j["prompt"][:140])
        print(len(jobs), "jobs")
        return 0
    if a.cmd == "finalize":
        for r in finalize(ROOT, only=a.only):
            print(r["status"], r["file"])
        print("确认只由项目方：uv run python tools/sop_owner.py plate <scene_id> \"原话\"")
        return 0
    r = emit(ROOT, only=a.only, force=a.force, draft=a.draft, dry_run=a.dry_run)
    doc = r.pop("doc", None)
    print(json.dumps(r, ensure_ascii=False))
    if doc:
        for j in doc["jobs"]:
            print(" ", j["id"], j["seed"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
