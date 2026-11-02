"""GPU 任务归属标签（GPUVIEW 2026-11-01，规则 K-OPS-G01：每个 GPU 任务都要带 comfy_tag）。

项目方原话：“实时展示gpu显卡做什么任务细节”。各 agent 直接往 ComfyUI 投任务，ns_api 分不清是谁的，面板只能写
“其他任务占用”。约定：投 ComfyUI 的 POST /prompt 时，在 body["extra_data"]["ns_tag"] 放一份标签——ComfyUI 会把
extra_data 原样留在 /queue 和 /history 的第 4 项里，面板（ns_api.gpu_live）读它显示“谁在做什么”。
client_id 不动（各工具按自己的 client_id 前缀认领队列，改了会认不出自己的任务）。

用法（只用标准库，tools/ 下脚本可直接 import）：
    from ns_agent import comfy_tag as CT
    body = {"prompt": g, "client_id": CLIENT + uuid.uuid4().hex[:8]}
    CT.attach(body, CT.make("VIDEO10", "video", episode=1, shot="S6", label="Ref2VA 24 步", attempt=2))

不经 ComfyUI 的 GPU 任务（TTS、训练…）写心跳：
    CT.heartbeat("VOICE10", "试听音色 · 林晚 候选3", kind="voice", server="gpu36", gpu=1, step=3, steps=10)
    … 结束时 CT.heartbeat_done(...) 或删掉；超过 ttl 秒没更新的心跳面板当作已结束。
心跳目录：本机 data/gpu_heartbeats/*.json，或 gpu36 上 /root/work/fredw/gpu_heartbeats/*.json（远端任务）。
字段说明见 docs/GPU_STATUS.md。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HEARTBEAT_DIR = ROOT / "data" / "gpu_heartbeats"
REMOTE_HEARTBEAT_DIR = {"gpu36": "/root/work/fredw/gpu_heartbeats"}

# kind → 人话（面板和“渲染任务”中心共用）
KIND_WORD = {
    "first_frame": "出首帧", "last_frame": "出尾帧", "frame": "出图", "video": "视频", "sheet": "资产图",
    "asset": "资产图", "voice": "试听音色", "tts": "配音", "bakeoff": "模型对比", "train": "训练",
    "edit": "修图", "script": "剧本", "storyboard": "分镜", "other": "任务",
}
# kind → 渲染任务中心的“类型”列
KIND_TYPE = {
    "first_frame": "首帧", "last_frame": "尾帧", "frame": "首帧", "video": "视频", "sheet": "资产图", "asset": "资产图",
    "voice": "音色", "tts": "音色", "bakeoff": "对比", "edit": "首帧", "script": "剧本", "storyboard": "分镜",
    "train": "训练", "other": "其他",
}
FIELDS = ("agent", "kind", "episode", "shot", "label", "attempt", "max_attempts", "idx", "total", "obj", "job")


def make(agent: str, kind: str, *, episode=None, shot=None, label: str | None = None, attempt: int | None = None,
         max_attempts: int | None = None, idx: int | None = None, total: int | None = None, obj: str | None = None,
         job: str | None = None) -> dict:
    """标签。agent = 会话 / 工具名（VIDEO10、IMGGEN、BAKEOFF…）；kind 见 KIND_WORD；episode 写数字；
    shot 写 "S4"；label 一句人话补充（例 "Ref2VA 24 步"）；attempt 第几次（1 起）；idx/total 批量进度（第 idx/total 张）；
    obj 对象（资产图写 "林晚 · 造型C"）；job 工具自己的作业 id（可回查）"""
    t = {"agent": str(agent), "kind": str(kind), "v": 1, "t": round(time.time(), 1)}
    for k, v in (("episode", episode), ("shot", shot), ("label", label), ("attempt", attempt),
                 ("max_attempts", max_attempts), ("idx", idx), ("total", total), ("obj", obj), ("job", job)):
        if v is not None and v != "":
            t[k] = v
    return t


def attach(body: dict, tag: dict | None) -> dict:
    """把标签放进 POST /prompt 的 body（extra_data.ns_tag）；tag=None 原样返回。返回同一个 body"""
    if tag:
        ed = body.get("extra_data")
        if not isinstance(ed, dict):
            ed = body["extra_data"] = {}
        ed["ns_tag"] = tag
    return body


def read(extra_data) -> dict | None:
    t = (extra_data or {}).get("ns_tag") if isinstance(extra_data, dict) else None
    return t if isinstance(t, dict) and t.get("agent") else None


# ------------------------------------------------------------------ 未标记任务：按 client_id / 输出名 / 模型推断
CLIENT_AGENT = [
    ("imggen-s10-", "IMGGEN"), ("video10-", "VIDEO10"), ("bakeoff-", "BAKEOFF"), ("series-", "SERIES"),
    ("reflock-", "REFLOCK"), ("consist", "CONSIST"), ("prompt-planc-", "PROMPT"), ("asset-", "ASSET"),
    ("ns_edit", "画布修图"), ("voice10", "VOICE10"),
    ("stylev2-", "STYLE-V2"), ("producer-", "PRODUCER"), ("imgmaster", "IMGMASTER"), ("vqagate", "VQAGATE"), ("promptfix", "PROMPTFIX"),
    ("debug-rsi", "DEBUG-RSI"), ("assetux", "ASSETUX"),        # 总调度 19:3x：client_id 前缀对得上已知 agent 就直接标名，不显示“未标记”
]
PREFIX_AGENT = [("assetmaster", "ASSETMASTER"), ("bakeoff", "BAKEOFF"), ("video10", "VIDEO10"), ("imggen", "IMGGEN"),
                ("reflock", "REFLOCK"), ("consist", "CONSIST"), ("longshot", "LONGSHOT"), ("series", "SERIES")]
_EP_SHOT = re.compile(r"ep(\d{1,2})[-_ ]?(S\d{1,3})", re.I)
_EP = re.compile(r"ep(\d{1,2})", re.I)


def _models(prompt: dict) -> list[str]:
    out = []
    for n in (prompt or {}).values():
        for k, v in ((n or {}).get("inputs") or {}).items():
            if isinstance(v, str) and k in ("unet_name", "ckpt_name", "model_name", "lora_name", "clip_name", "vae_name"):
                out.append(v)
    return out


def _prefixes(prompt: dict) -> list[str]:
    return [str(n["inputs"]["filename_prefix"]) for n in (prompt or {}).values()
            if isinstance((n or {}).get("inputs"), dict) and n["inputs"].get("filename_prefix")]


def steps_of(prompt: dict) -> int | None:
    """采样步数（KSampler / BasicScheduler / 各种 Scheduler 的 steps 输入；取最大）"""
    best = None
    for n in (prompt or {}).values():
        v = ((n or {}).get("inputs") or {}).get("steps")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            best = max(best or 0, int(v))
    return best


def family(prompt: dict) -> str:
    """模型家族人话：Ref2VA / H3 视频 / Qwen-Image 2.1 / FLUX …"""
    ms = " ".join(_models(prompt)).lower()
    cls = " ".join(str((n or {}).get("class_type", "")) for n in (prompt or {}).values()).lower()
    if "ref2va" in ms:
        return "Ref2VA"
    if "minimax_h3" in ms or "h3" in cls and "video" in cls:
        return "H3 视频"
    if "wan" in ms and ("video" in cls or "wan" in cls):
        return "Wan 视频"
    if "qwen_image_edit" in ms:
        return "Qwen-Edit"
    if "qwen_image_2.1_turbo" in ms:
        return "Qwen-Image 2.1 Turbo"
    if "qwen_image" in ms:
        return "Qwen-Image 2.1"
    if "flux" in ms:
        return "FLUX"
    if "sdxl" in ms or "pony" in ms or "illustrious" in ms:
        return "SDXL"
    if "vibevoice" in ms or "tts" in cls or "audio" in cls and "video" not in cls:
        return "语音"
    return "ComfyUI"


def is_video(prompt: dict) -> bool:
    ms = " ".join(_models(prompt)).lower()
    cls = " ".join(str((n or {}).get("class_type", "")) for n in (prompt or {}).values())
    return "minimax_h3" in ms or "ref2va" in ms or "VHS_VideoCombine" in cls or "SaveVideo" in cls or "CreateVideo" in cls


def infer(prompt: dict, extra_data: dict | None) -> dict:
    """没有 ns_tag 的任务：按 client_id 前缀、输出文件名、模型推断一份标签（inferred=True）"""
    cid = str((extra_data or {}).get("client_id") or "")
    pre = " ".join(_prefixes(prompt))
    agent = next((a for p, a in CLIENT_AGENT if cid.startswith(p)), None)
    low = pre.lower()
    by_prefix = next((a for p, a in PREFIX_AGENT if low.startswith(p) or f"/{p}" in low or low.startswith(p + "_")), None)
    if by_prefix and (agent in (None, "IMGGEN") or by_prefix == "ASSETMASTER"):
        agent = by_prefix               # ASSETMASTER 借 IMGGEN 的工具投，输出目录 assetmaster_* 才认得出
    fam = family(prompt)
    vid = is_video(prompt)
    if "bakeoff" in low or agent == "BAKEOFF":
        kind = "bakeoff"
    elif vid:
        kind = "video"
    elif re.search(r"_(last|end|tail)(_|$)|尾帧", pre, re.I):
        kind = "last_frame"
    elif _EP_SHOT.search(pre) or "frames" in low:
        kind = "first_frame"
    elif re.search(r"sheet|look|item_|scene_|char|asset", low):
        kind = "sheet"
    else:
        kind = "frame"
    t = {"agent": agent or "未标记", "kind": kind, "inferred": True, "family": fam}
    m = _EP_SHOT.search(pre)
    if m:
        t["episode"], t["shot"] = int(m.group(1)), m.group(2).upper()
    elif _EP.search(pre):
        t["episode"] = int(_EP.search(pre).group(1))
    if kind == "sheet":
        stem = pre.rsplit("/", 1)[-1]
        stem = re.sub(r"_s\d+$", "", stem)
        t["obj"] = stem
    return t


def tag_of(prompt: dict, extra_data: dict | None) -> dict:
    """先读 ns_tag，没有就推断；都补上 family / steps"""
    t = read(extra_data)
    t = dict(t) if t else infer(prompt, extra_data)
    t.setdefault("family", family(prompt))
    st = steps_of(prompt)
    if st:
        t.setdefault("steps", st)
    return t


def _ep_word(t: dict) -> str:
    ep, sh = t.get("episode"), t.get("shot")
    try:
        e = f"第{int(ep)}集" if ep not in (None, "") else ""
    except (TypeError, ValueError):
        e = str(ep)
    return " ".join(x for x in (e, str(sh) if sh else "") if x)


def describe(t: dict) -> str:
    """一句人话：出首帧 · 第3集 S4 · 第2次重试 / 视频 · 第1集 S6 · Ref2VA 24 步 / 模型对比 BAKEOFF 第 212/391 张"""
    kind = t.get("kind") or "other"
    word = KIND_WORD.get(kind, kind)
    parts = [word]
    if kind == "bakeoff" and t.get("agent"):
        parts = [f"{word} {t['agent']}"]
    where = _ep_word(t)
    if where:
        parts.append(where)
    if t.get("obj"):
        parts.append(str(t["obj"]))
    if t.get("label"):
        parts.append(str(t["label"]))
    elif kind == "video" and (t.get("family") or t.get("steps")):
        parts.append(" ".join(x for x in (t.get("family"), f"{t['steps']} 步" if t.get("steps") else "") if x))
    if t.get("idx") and t.get("total"):
        parts.append(f"第 {t['idx']}/{t['total']} 张")
    a = t.get("attempt")
    if isinstance(a, int) and a > 1:
        parts.append(f"第{a - 1}次重试")
    s = " · ".join(parts)
    if t.get("inferred"):
        s = f"未标记任务 · {t.get('family') or 'ComfyUI'} {word}" + (f" · {where}" if where else "") + \
            (f" · {t['obj']}" if t.get("obj") else "")
    return s


# ------------------------------------------------------------------ 非 ComfyUI GPU 任务的心跳
def heartbeat(agent: str, label: str, *, kind: str = "other", server: str | None = None, gpu=None,
              step: int | None = None, steps: int | None = None, pct: float | None = None, eta_s: float | None = None,
              episode=None, shot=None, thumb: str | None = None, hb_id: str | None = None, ttl: int = 120,
              state: str = "running", directory: Path | str | None = None) -> Path:
    """写一份心跳 JSON（原子替换）。server/gpu 写在哪张卡上（例 "gpu36", 1）；step/steps 或 pct 是进度；
    thumb 本机图片路径（相对项目根）；ttl 秒内没再写 → 面板当作已结束。返回文件路径"""
    d = Path(directory) if directory else HEARTBEAT_DIR
    d.mkdir(parents=True, exist_ok=True)
    hid = hb_id or f"{agent}-{os.getpid()}"
    p = d / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', hid)}.json"
    rec = {"agent": agent, "label": label, "kind": kind, "server": server, "gpu": gpu, "step": step, "steps": steps,
           "pct": pct, "eta_s": eta_s, "episode": episode, "shot": shot, "thumb": thumb, "state": state,
           "ttl": ttl, "pid": os.getpid(), "updated": time.time()}
    started = None
    try:
        started = json.loads(p.read_text(encoding="utf-8")).get("started")
    except (OSError, ValueError):
        pass
    rec["started"] = started or time.time()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def heartbeat_done(agent: str, hb_id: str | None = None, directory: Path | str | None = None) -> None:
    d = Path(directory) if directory else HEARTBEAT_DIR
    hid = hb_id or f"{agent}-{os.getpid()}"
    try:
        (d / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', hid)}.json").unlink()
    except OSError:
        pass
