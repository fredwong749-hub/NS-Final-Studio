"""
G2 母版候选自动生成（TASKS T43）：新剧角色上传参考图后，按 3 档写实强度 × 2 个种子生成候选**任务**（不出图），
写进 data/jobs/queue/*.json（gpu_grab 队列消费的格式，同 data/jobs/gpu3_char_variety_20261030.json）。

配方 = 林晚 CM_s1 流程（golden/assets/notes.md「项目方改方向」）+ SOP_parameters S2「身份母版写实配方」：
  Qwen-Image 2.1 Base，35 步，cfg 3.0，texture-fix VAE，第二遍 refine 1.5× / 12 步 / denoise 0.30；
  krea2_film_texture 写实质感；参考图是风格化（AI 插画/动漫感）时加 Anything2RealCharacters；
  灰底（#808080）、中性素色服装、不带项链/首饰/道具；提示词不含 visual_bible banned_words，加 skin_terms；
  QC v3（NudeNet + CLIP v2 + VL 裁决）硬失败；参考图记为「AI 生成的虚构成年人，≥22 岁」。

三档写实强度（每档 2 个种子，共 6 张）：
  CL 轻  Anything2Real 0.25 + krea2 0.3     （林晚 CL 档）
  CM 中  Anything2Real 0.45 + krea2 0.4     （林晚最终选定的 CM_s1 档）
  CS 重  Anything2Real 0.8  + krea2 0.5     （SOP S2 锁定的身份母版写实配方）
  参考图本身已是照片质感（reference_kind=photo）→ 不加 Anything2Real，只用 krea2 0.3 / 0.4 / 0.5。

规则：
- 只有项目方在人物卡上勾选了「此角色为 AI 生成的虚构成年人」（project.json characters.<id>.confirmed）才出任务；
  角色描述写明年龄 <22 一律拒绝。
- **从不自动选母版**：本模块不写 plates/master.png、不登记 LoRA；候选落在 assets/characters/<id>/candidates/，
  由项目方在 G2 挑一张。
- 幂等：同一角色 + 同一参考图（sha）只出一次队列文件（data/jobs/ 下任何位置已有同名文件即跳过），--force 重出。

本模块只读项目文件（wizard 写的 project.json / visual_bible.toml），不导入渲染代码。
"""
from __future__ import annotations

import hashlib
import re
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ns_api.project_ctx import REPO, ProjectContext, write_json

QUEUE_DIR = REPO / "data" / "jobs" / "queue"
JOBS_DIR = REPO / "data" / "jobs"

MODEL = "qwen_image_2.1_int8_convrot.safetensors"
VAE = "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors"
KREA2 = "krea2_film_texture_qwen21.safetensors"
A2R = "Qwen2.1_Anything2RealCharacters.safetensors"
STEPS = 35
CFG = 3.0
SIZE = (1024, 1536)
REFINE = {"scale": 1.5, "steps": 12, "denoise": 0.3}
LORA_CAP = 1.6                       # SOP S3-F6：同一张图所有 LoRA 合计 ≤1.6
MIN_AGE = 22
SEEDS_PER_TIER = 2
QC = "QC v3 hard fail (NudeNet + CLIP v2 + VL verdict); failed images are deleted, not kept"
STATUS = "candidate (owner picks one at G2; no master/LoRA until picked)"


@dataclass(frozen=True)
class Tier:
    key: str           # CL / CM / CS
    label: str
    a2r: float         # Anything2Real 强度（仅风格化参考）
    krea2: float


TIERS = (
    Tier("CL", "light", 0.25, 0.3),
    Tier("CM", "mid", 0.45, 0.4),
    Tier("CS", "strong", 0.8, 0.5),
)

NEGATIVE = ("磨皮, 塑料皮肤, 蜡像, CGI, 3D render, airbrushed, doll face, 动漫, 插画, 多余手指, 手指融合, 肢体变形, "
            "未成年人外观, 儿童, 校服, 裸体, 赤裸上身, 项链, 首饰, 手表, 道具, 花, 文字, 水印, 低清")

DEFAULT_BANNED = ["娃娃感", "精致完美", "完美无瑕", "网红脸", "网红", "纯欲", "斩男"]
DEFAULT_SKIN = "真实皮肤质感，可见细小毛孔与细软绒毛，自然的轻微不对称，眼睛为真实人眼大小"
CAMERA = "真实相机拍摄的原片，未修图，皮肤有真实纹理与细小毛孔，shot on Leica M11, 50mm, Kodak Portra 400 film look"


class G2Blocked(Exception):
    """不能为该角色出候选（未确认 AI 虚构成年人 / 没有参考图 / 年龄 <22）"""


# ------------------------------------------------------------------ 读取

def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_file(p: Path) -> str | None:
    try:
        return _sha_bytes(p.read_bytes())
    except OSError:
        return None


def bible(ctx: ProjectContext) -> tuple[dict, str | None]:
    p = ctx.visual_bible
    try:
        raw = p.read_bytes()
    except OSError:
        return {}, None
    try:
        return tomllib.loads(raw.decode("utf-8")), _sha_bytes(raw)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}, _sha_bytes(raw)


def repo_path(ctx: ProjectContext, rel: str) -> str:
    """项目内相对路径 → 仓库相对路径（gpu3 镜像按仓库布局找文件）；项目不在仓库内（测试）时给绝对路径"""
    p = (ctx.root / rel).resolve()
    try:
        return p.relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def parse_age(text: str) -> int | None:
    m = re.search(r"(\d{1,3})\s*(?:岁|years? old|yo\b)", text or "")
    return int(m.group(1)) if m else None


def parse_gender(text: str) -> str:
    t = text or ""
    if re.search(r"女|她|woman|female|girl", t, re.I):
        return "woman"
    if re.search(r"男|他|\bman\b|male", t, re.I):
        return "man"
    return "person"


def strip_banned(text: str, banned: list[str]) -> str:
    for w in sorted(banned, key=len, reverse=True):
        text = text.replace(w, "")
    return re.sub(r"[，,]\s*[，,]", "，", text).strip("，, ")


# ------------------------------------------------------------------ 组装

def tier_loras(tier: Tier, stylised: bool) -> list[list]:
    loras = ([[A2R, tier.a2r]] if stylised else []) + [[KREA2, tier.krea2]]
    total = sum(s for _, s in loras)
    if total > LORA_CAP:                       # 按比例缩小（S3-F6）
        loras = [[n, round(s * LORA_CAP / total, 3)] for n, s in loras]
    return loras


def build_prompt(c: dict, gender: str, age: int | None, banned: list[str], skin: str) -> str:
    name = c.get("name") or c.get("id")
    who = {"woman": "an adult woman", "man": "an adult man"}.get(gender, "an adult")
    age_txt = f"{age} years old" if age else f"in the twenties, at least {MIN_AGE} years old"
    clothes = "a plain neutral grey crew-neck knit top"
    desc = strip_banned(c.get("description") or "", banned)
    p = (f"Figure 1 is the identity reference of {name}, {who} ({age_txt}; fictional, AI-generated). "
         f"Character notes: {desc}. "
         "Keep the face, hairstyle, hair colour, makeup and the overall feeling of Figure 1; only change the rendering "
         "into the texture of a real photograph (只改变质感，不改变内容). Do NOT copy Figure 1's pose, hands, necklace, "
         "jewellery, flowers, props, background or lighting. "
         f"Head-and-shoulders to waist portrait, front view, neutral expression, looking into the lens, wearing {clothes}, "
         "no necklace, no jewellery, no watch, nothing in the hands. Plain neutral grey seamless studio backdrop (#808080), "
         "soft even light, 50mm lens at f/8. Unretouched real photo. "
         f"{skin}。{CAMERA}")
    return strip_banned(p, banned)


def seed_for(cid: str, ref_sha: str, tier: str, i: int) -> int:
    return int(_sha_bytes(f"g2|{cid}|{ref_sha}|{tier}|{i}".encode())[:12], 16)


def queue_name(ctx: ProjectContext, cid: str, ref_sha: str) -> str:
    return f"g2_{ctx.slug}_{cid}_{ref_sha[:10]}.json"


def already_queued(name: str, jobs_dir: Path = JOBS_DIR) -> Path | None:
    return next(iter(sorted(jobs_dir.rglob(name))), None) if jobs_dir.is_dir() else None


def build(ctx: ProjectContext, cid: str, ref: str | None = None, reference_kind: str | None = None,
          requested_by: str = "fredw-d9") -> dict:
    """返回一个队列文件内容（不写盘）。不满足条件抛 G2Blocked。"""
    chars = ctx.settings().get("characters", {})
    if cid not in chars:
        raise G2Blocked(f"没有角色 {cid}")
    c = chars[cid]
    refs = c.get("references") or []
    if not refs:
        raise G2Blocked(f"{cid}：还没有上传参考图")
    if not c.get("confirmed"):
        raise G2Blocked(f"{cid}：项目方还没勾选「此角色为 AI 生成的虚构成年人」，不出候选")
    rel = ref or refs[-1]
    if rel not in refs:
        raise G2Blocked(f"{cid}：参考图 {rel} 不在人物卡上")
    ref_path = ctx.resolve_inside(rel)
    ref_sha = _sha_file(ref_path)
    if not ref_sha:
        raise G2Blocked(f"{cid}：参考图文件不存在 {rel}")
    text = f"{c.get('name', '')} {c.get('description', '')}"
    age = parse_age(text)
    if age is not None and age < MIN_AGE:
        raise G2Blocked(f"{cid}：角色描述年龄 {age} 岁 < {MIN_AGE}，不出候选")
    gender = parse_gender(c.get("description") or "")
    kind = reference_kind or c.get("reference_kind") or "stylised"
    if kind not in ("stylised", "photo"):
        raise ValueError("reference_kind 只能是 stylised / photo")
    stylised = kind == "stylised"

    vb, bible_sha = bible(ctx)
    realism = vb.get("realism", {}) if isinstance(vb, dict) else {}
    banned = list(realism.get("banned_words") or DEFAULT_BANNED)
    skin = realism.get("skin_terms") or DEFAULT_SKIN
    prompt = build_prompt(c, gender, age, banned, skin)
    out_dir = repo_path(ctx, f"assets/characters/{cid}/candidates") + "/"
    ref_record = {"path": repo_path(ctx, rel), "sha256": ref_sha, "kind": kind,
                  "ai_generated_fictional_adult": True, "min_age": MIN_AGE, "age_stated": age,
                  "approved_by": c.get("approved_by"), "approved_at": c.get("approved_at")}
    jobs = []
    for tier in TIERS:
        for i in range(SEEDS_PER_TIER):
            jobs.append({
                "id": f"g2_{ctx.slug}_{cid}_{tier.key}_s{i}",
                "mode": "edit", "refs": [ref_record["path"]],
                "model": MODEL, "steps": STEPS, "cfg": CFG, "size": list(SIZE),
                "lora": tier_loras(tier, stylised), "vae": VAE, "refine": dict(REFINE),
                "negative": NEGATIVE, "bible_sha256": bible_sha,
                "reference_source": f"{ref_record['path']} (sha256 {ref_sha[:12]}…; owner-confirmed AI-generated "
                                    f"fictional adult ≥{MIN_AGE})",
                "reference": ref_record,
                "project": ctx.slug, "character": cid, "tier": tier.key, "tier_label": tier.label,
                "file": f"{cid}_{tier.key}_s{i}.png", "prompt": prompt, "seed": seed_for(cid, ref_sha, tier.key, i),
                "preset": f"G2_{tier.key}", "qc": QC, "status": STATUS, "out_dir": out_dir,
            })
    return {
        "requested_by": requested_by,
        "kind": "g2_master_candidates",
        "purpose": (f"T43 G2 master candidates for {c.get('name', cid)} ({ctx.name}): 3 realism tiers × "
                    f"{SEEDS_PER_TIER} seeds, Lin Wan CM_s1 recipe; owner picks the master"),
        "gpu": "gpu3 idle GPU (never GPU2)",
        "selection": "owner picks one candidate at G2; this tool never writes plates/master.png or a LoRA",
        "project": ctx.slug, "character": cid, "reference": ref_record,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "jobs": jobs,
    }


def emit(ctx: ProjectContext, cid: str, *, ref: str | None = None, reference_kind: str | None = None,
         force: bool = False, dry_run: bool = False, queue_dir: Path = QUEUE_DIR,
         jobs_dir: Path = JOBS_DIR) -> dict:
    """生成并写入队列文件。返回 {"status": queued|exists|dry_run, "path", "jobs"}。"""
    doc = build(ctx, cid, ref=ref, reference_kind=reference_kind)
    name = queue_name(ctx, cid, doc["reference"]["sha256"])
    prev = already_queued(name, jobs_dir)
    if prev and not force:
        return {"status": "exists", "path": prev.as_posix(), "jobs": len(doc["jobs"])}
    path = queue_dir / name
    if dry_run:
        return {"status": "dry_run", "path": path.as_posix(), "jobs": len(doc["jobs"]), "doc": doc}
    write_json(path, doc)
    return {"status": "queued", "path": path.as_posix(), "jobs": len(doc["jobs"])}


def scan(ctx: ProjectContext, **kw) -> list[dict]:
    """「上传参考图后」的触发点：对每个已确认、有参考图的角色出一次（已出过的跳过）；未满足条件的给原因。"""
    out = []
    for cid in ctx.settings().get("characters", {}):
        try:
            out.append({"character": cid, **{k: v for k, v in emit(ctx, cid, **kw).items() if k != "doc"}})
        except G2Blocked as e:
            out.append({"character": cid, "status": "blocked", "reason": str(e)})
    return out


def candidates_status(ctx: ProjectContext, cid: str) -> dict:
    """候选图落盘情况（只读）：哪些已出、母版是否已由项目方选定"""
    d = ctx.assets_dir / "characters" / cid
    files = sorted(p.name for p in (d / "candidates").glob(f"{cid}_C?_s*.png")) if (d / "candidates").is_dir() else []
    return {"character": cid, "candidates": files, "master_exists": (d / "plates" / "master.png").is_file()}
