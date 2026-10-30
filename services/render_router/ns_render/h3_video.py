"""
v1 视频（api_v1_contract §D，fredw-92/W3）：定稿首帧 + 定稿尾帧 → gpu3 GPU3 ComfyUI 的 MiniMax H3 FL2VA。

- 图与 gpu3 生产渲染器一致（weita_render.h3_graph + data/run/weita/PIPELINE_LOCKED.json，2026-10-30 核对）：
  DiT minimax_h3_fl2va_pruned_int8_convrot、Turbo LoRA 8step v1.1 768p（强度 1.0）、shift 6/3（采样与调度都过）、
  euler/simple、8 步、768×1344、24 fps、首尾帧 center-crop + lanczos；文本编码器 qwen3vl_32b_minimax_h3_nvfp4_awq、
  视频 VAE int8_convrot、音频 VAE fp32（gpu3 :8191 object_info 均在列）。
- 提示词：请求 prompt_override > 项目方覆盖（edits.json h3_prompt_override，未过期）> 剧本 **H3提示词**（编译器
  resolve_music 已解析配乐）。原样传；只有时长改了时把系统生成的第一行对齐句按新帧数重算（结构行，不是内容）。
- 帧数：秒数 → ns_schema.h3_lint.frames_for_seconds（17k+5，124–362）。
- 本模块不做内容检测 / 成人拦截。
"""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import replace
from pathlib import Path

from ns_schema.edits import Take
from ns_schema.h3_lint import ALIGN_PREFIX, alignment_line, frames_for_seconds

from . import pipeline as P
from . import workflows as W
from . import comfy_client as CC
from .comfy_client import ComfyError

import os

# fredw-92/D1：3090（24 GB，ComfyUI --reserve-vram 1）上 768×1344 的 H3 实测能跑到 192 帧（8 s，峰值约 22.6 GB）；
# 294 帧（12 s）在 SamplerCustomAdvanced 必 OOM（已分配 19.13 GiB + 再要 4.97 GiB > 23.56 GiB，ep02-S8 两次）。
# 超过上限的镜头按 gpu3 修复规则 oom.lower_cost 的做法“出短一格、剪辑里按片长走”（G13：片长以 H3 实际为准），
# params 记 frames_requested / frames_capped。上限可用环境变量 NS_H3_MAX_FRAMES 调（须在 17k+5 网格上）。
SAFE_MAX_FRAMES_DEFAULT = 192


def safe_max_frames() -> int:
    try:
        v = int(os.environ.get("NS_H3_MAX_FRAMES") or SAFE_MAX_FRAMES_DEFAULT)
    except ValueError:
        v = SAFE_MAX_FRAMES_DEFAULT
    v = max(W.H3_FRAMES_MIN, min(v, W.H3_FRAMES_MAX))
    return v - ((v - 5) % 17)          # 向下对齐到 17k+5


def frames_for(seconds: float) -> tuple[int, int]:
    """(实际出的帧数, 剧本时长要的帧数)：显存上限内取 frames_for_seconds，超了取上限"""
    want = frames_for_seconds(seconds)
    return min(want, safe_max_frames()), want


DEFAULT_STEPS = W.H3Model().steps
DEFAULT_LORA_STRENGTH = dict(W.H3Model().loras)[W.H3_TURBO_8STEP_768P]
TIMEOUT_S = 3600

# fredw-92/VB：请求附加的视频 LoRA（串在 Turbo LoRA 和剧本视频 LoRA 之后）。强度范围、可选清单在 config/render_quality.json
EXTRA_LORA_MIN, EXTRA_LORA_MAX = 0.0, 1.5


def optional_video_loras(path: Path | None = None) -> list[dict]:
    """config/render_quality.json 的 optional_video_loras（画布“附加视频 LoRA”下拉用）；读不到 → []"""
    import json
    try:
        q = json.loads(Path(path or (P.ROOT / "config" / "render_quality.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [dict(x) for x in (q.get("optional_video_loras") or []) if isinstance(x, dict) and x.get("name")]


def merge_loras(script_loras, extra) -> list[tuple[str, float]]:
    """剧本视频 LoRA + 请求附加 LoRA；同名时以请求的强度为准（不重复串两次），顺序：剧本在前、附加在后"""
    extra = [(str(n), float(s)) for n, s in (extra or [])]
    names = {n for n, _ in extra}
    return [(n, float(s)) for n, s in script_loras if n not in names] + extra


class FramesNotLocked(ValueError):
    """首尾帧没定稿；missing = ["first"] / ["last"] / 两个都有"""

    def __init__(self, missing: list[str], detail: str):
        super().__init__(detail)
        self.missing = missing


_SHA_CACHE: dict[tuple, str] = {}


def file_sha(path: Path) -> str:
    """文件内容 sha256 前 16 位（按 路径 + mtime + 大小 缓存：集摘要每次都要比对）"""
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key not in _SHA_CACHE:
        _SHA_CACHE[key] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return _SHA_CACHE[key]


def locked_n(takes: dict, stage: str) -> int | None:
    """定稿版本号：takes.json 顶层 locked[stage]（W2）或 take.locked 为真（兼容）"""
    lk = takes.get("locked") or {}
    keys = ("image", "first") if stage == "image" else (stage,)
    for k in keys:
        if isinstance(lk, dict) and lk.get(k) is not None:
            return int(lk[k])
    t = next((t for t in reversed(takes.get("takes", [])) if t.get("stage") == stage and t.get("locked")), None)
    return t["n"] if t else None


def locked_frames(shot_id: str) -> dict:
    """{"first": {n, file, sha}, "last": {...}}；缺哪个就抛 FramesNotLocked 写明"""
    takes = P.load_takes(shot_id)
    out, missing, why = {}, [], []
    for key, stage, label in (("first", "image", "首帧"), ("last", "last", "尾帧")):
        n = locked_n(takes, stage)
        t = next((t for t in takes["takes"] if t["stage"] == stage and t["n"] == n), None) if n is not None else None
        if t is None:
            missing.append(key)
            why.append(f"{label}未定稿")
            continue
        p = P.DATA / t["file"]
        if not p.is_file():
            missing.append(key)
            why.append(f"{label}定稿文件不存在（{t['file']}）")
            continue
        out[key] = {"n": n, "file": t["file"], "sha": file_sha(p)}
    if missing:
        raise FramesNotLocked(missing, "；".join(why) + "（出视频要求首帧、尾帧都已定稿）")
    return out


UPLOAD_TIMEOUT_S = 900   # 笔记本上行慢（实测 8–25 KB/s 时 3 MB PNG 超过 ComfyClient 默认 60 s）


def keyframe_file(path: Path, size=None) -> Path:
    """首尾帧预先 center-crop + lanczos 到视频画布（与图里 ImageScale crop=center 相同，图里那步变成原尺寸直通），
    文件小一半，上传快；按内容 sha 缓存在 data/renders/_h3_keyframes/"""
    from PIL import Image
    w, h = size or P.VIDEO_SIZE
    out = P.RENDERS / "_h3_keyframes" / f"{file_sha(path)}_{w}x{h}.png"
    if out.is_file():
        return out
    im = Image.open(path).convert("RGB")
    sw, sh = im.size
    scale = max(w / sw, h / sh)
    rw, rh = max(w, round(sw * scale)), max(h, round(sh * scale))
    im = im.resize((rw, rh), Image.LANCZOS)
    left, top = (rw - w) // 2, (rh - h) // 2
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.png")
    im.crop((left, top, left + w, top + h)).save(tmp, optimize=True)
    tmp.replace(out)
    return out


def upload_once(client, path: Path, subfolder: str = "ns_final", size=None) -> str:
    """首尾帧 → LoadImage 名。真 ComfyClient（fredw-92/F1）：path 是 gpu3 本实例的输出原样 → [output] 引用 +
    图内 center-crop 缩放，不上传；否则上传 keyframe_file（JPEG q95、输入目录已有同内容跳过、≥900 s）。
    假客户端：ComfyUI 输入目录里已有同内容文件（upload_image 按 sha 命名）就不再上传"""
    if hasattr(client, "input_image"):
        return client.input_image(path, subfolder, size=tuple(size or P.VIDEO_SIZE), crop="center",
                                  prepare=lambda: keyframe_file(path, size))
    path = keyframe_file(path, size)
    name = hashlib.sha256(path.read_bytes()).hexdigest()[:16] + path.suffix.lower()
    try:
        client._request(f"/view?filename={name}&subfolder={subfolder}&type=input")
        return f"{subfolder}/{name}"
    except Exception:  # noqa: BLE001  没有 / 查不到 → 上传
        pass
    old = getattr(client, "timeout", None)
    if old is not None:
        client.timeout = max(old, UPLOAD_TIMEOUT_S)
    try:
        return client.upload_image(path, subfolder)
    finally:
        if old is not None:
            client.timeout = old


def resolve_prompt(script, shot_id: str, prompt_override: str | None, loras=frozenset()) -> tuple[str, str, object]:
    """→ (提示词原文, 来源 request|owner_edit|script|laptop, compiled)"""
    c = P.compile_with_edits(script, shot_id, set(loras))
    if prompt_override and prompt_override.strip():
        return prompt_override, "request", c
    edit = P.load_edit(shot_id)
    ov = edit.h3_prompt_override
    if ov and ov.text.strip():
        _, s = P.find_shot(script, shot_id)
        stale = ov.script_sha != (hashlib.sha256(s.h3_prompt.encode("utf-8")).hexdigest()
                                  if getattr(s, "h3_prompt", None) else None)
        if not stale:
            return ov.text, "owner_edit", c
    return c.video_prompt, c.h3_prompt_source or "laptop", c


def realign(prompt: str, frames: int) -> str:
    """只换第一行系统对齐句（秒数随帧数变）；不是 H3 结构就原样返回"""
    head, sep, rest = prompt.partition("\n")
    if not head.startswith(ALIGN_PREFIX):
        return prompt
    return alignment_line(frames) + sep + rest


def shot_seconds(script, shot_id: str) -> float:
    _, s = P.find_shot(script, shot_id)
    return float(getattr(s, "duration", None) or 10)


def build(prompt: str, first: str, last: str, frames: int, seed: int, prefix: str, *, steps: int = DEFAULT_STEPS,
          lora_strength: float = DEFAULT_LORA_STRENGTH, extra_loras=()) -> dict:
    m = replace(W.H3Model(), steps=int(steps), loras=((W.H3_TURBO_8STEP_768P, float(lora_strength)),))
    return W.h3_fl2va(prompt, first, *P.VIDEO_SIZE, frames, seed, prefix, m=m, loras=list(extra_loras),
                      last_frame=last)


class VramSampler:
    """出视频期间每 2 s 读一次 ComfyUI /system_stats，记显存峰值（GB）"""

    def __init__(self, client, every_s: float = 2.0):
        self.client, self.every, self.peak, self.total = client, every_s, None, None
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                d = (self.client.system_stats().get("devices") or [{}])[0]
                used = (d["vram_total"] - d["vram_free"]) / 2**30
                self.total = round(d["vram_total"] / 2**30, 1)
                self.peak = round(max(self.peak or 0, used), 2)
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(self.every)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()


def render(client, script, shot_id: str, *, seed: int | None = None, steps: int | None = None,
           seconds: float | None = None, lora_strength: float | None = None, prompt_override: str | None = None,
           parent: int | None = None, job: dict | None = None, gpu: int = 3, timeout_s: float = TIMEOUT_S,
           wait=None, extra_loras=None) -> Take:
    """出一版视频并存为 take（stage=video，带 params / parent），设为当前。wait(client, job, pid, timeout) 可取消"""
    frames_in = locked_frames(shot_id)
    avail = P.available_loras(client)
    prompt, src, c = resolve_prompt(script, shot_id, prompt_override, avail)
    req_loras = [(str(n), float(st)) for n, st in (extra_loras or [])]
    missing = [n for n, _ in req_loras if n not in avail]
    if missing:   # 提交时校验过；这里防止排队期间道上的 LoRA 列表变了
        raise ComfyError(f"附加 LoRA 不在 GPU{gpu} 的 LoRA 列表里：{', '.join(missing)}")
    vloras = merge_loras(c.video_loras, req_loras)
    secs = float(seconds) if seconds else shot_seconds(script, shot_id)
    frames, frames_want = frames_for(secs)
    prompt = realign(prompt, frames)
    steps = int(steps or DEFAULT_STEPS)
    ls = DEFAULT_LORA_STRENGTH if lora_strength is None else float(lora_strength)
    with P.shot_lock(shot_id):
        n = P._next_n(shot_id, "video")
    s = int(seed) if seed is not None else P.seed_for(shot_id + "/v", n)
    d = P.shot_dir(shot_id)
    t_up = time.monotonic()
    first = upload_once(client, P.DATA / frames_in["first"]["file"])
    last = upload_once(client, P.DATA / frames_in["last"]["file"])
    upload_s = round(time.monotonic() - t_up, 1)
    wf = build(prompt, first, last, frames, s, f"ns_final/{shot_id}_video", steps=steps, lora_strength=ls,
               extra_loras=vloras)
    problems = client.check(wf)
    if problems:
        raise ComfyError("工作流检查不通过：" + "；".join(problems))
    t0 = time.monotonic()
    with VramSampler(client) as vram:
        pid = client.submit(wf)
        if job is not None:
            job["prompt_id"] = pid
        entry = wait(client, job, pid, timeout_s) if wait else client.wait(pid, timeout_s)
    secs_run = round(time.monotonic() - t0, 1)
    item = next(f for f in client.output_files(entry) if f["filename"].endswith(".mp4"))
    # 文件名带任务 id：两条道同时出同一镜视频时 n 可能相同，不能互相覆盖（F3 审计；_add_take 会顺延 n）
    from .frame_edit import unique_tag
    base = f"renders/{d.relative_to(P.RENDERS).as_posix()}/takes/video_{n:03d}_{unique_tag(job)}"
    for i in range(3):   # 隧道抖动时重试下载（prompt 已跑完，不重渲）
        try:
            client.download(item, P.DATA / f"{base}.mp4")
            break
        except ComfyError:
            if i == 2:
                raise
            time.sleep(5)
    lf = P.extract_last_frame(P.DATA / f"{base}.mp4", P.DATA / f"{base}_last.png")
    m = W.H3Model()
    params = {"seed": s, "steps": steps, "seconds": secs, "frames": frames, "lora_strength": ls,
              "frames_requested": frames_want, "frames_capped": frames < frames_want,
              "prompt_source": src, "prompt_override": prompt_override or None,
              "first": frames_in["first"], "last": frames_in["last"], "gpu": gpu,
              "model": {"unet": m.unet, "clip": m.clip, "video_vae": m.video_vae, "audio_vae": m.audio_vae,
                        "turbo_lora": W.H3_TURBO_8STEP_768P, "extra_loras": [list(x) for x in vloras],
                        "shift": list(W.expected_shift([(W.H3_TURBO_8STEP_768P, ls), *vloras])),
                        "sampler": m.sampler, "scheduler": m.scheduler, "size": list(P.VIDEO_SIZE), "fps": m.fps},
              "loras": [{"name": n, "strength": st} for n, st in req_loras],
              "render_s": secs_run, "upload_s": upload_s, "vram_peak_gb": vram.peak, "vram_total_gb": vram.total}
    take = Take(n=n, stage="video", file=f"{base}.mp4", seed=s, prompt=prompt, seconds=secs_run, frames=frames,
                created_at=P.now(), last_frame=f"{base}_last.png" if lf else None, workflow="h3_fl2va",
                parent=parent, from_first=frames_in["first"]["n"], gpu=gpu,
                job_id=(job or {}).get("id"), params=params,
                remote=CC.remote_info(client, P.DATA / f"{base}.mp4"))
    P._add_take(shot_id, take)
    P._clear_error(shot_id)
    return take


def stale_reasons(take: dict, takes: dict) -> list[str]:
    """视频版本：渲染时的首尾帧 ≠ 当前定稿（版本号或文件内容变了）→ 过期原因"""
    p = take.get("params") or {}
    out = []
    for key, stage, label in (("first", "image", "定稿首帧已换"), ("last", "last", "定稿尾帧已换")):
        rec = p.get(key)
        if not rec:
            continue
        n = locked_n(takes, stage)
        if n is None:
            out.append(label.replace("已换", "已取消定稿"))
            continue
        if n != rec.get("n"):
            out.append(label)
            continue
        t = next((t for t in takes.get("takes", []) if t["stage"] == stage and t["n"] == n), None)
        path = P.DATA / t["file"] if t else None
        if path and path.is_file() and rec.get("sha") and file_sha(path) != rec["sha"]:
            out.append(label)
    return out
