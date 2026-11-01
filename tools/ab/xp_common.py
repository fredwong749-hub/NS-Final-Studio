"""P2 画质实验公用：道（lane）空闲判定、ComfyUI 直交、日志。只写 data/ab/，不建 take、不动生产数据。
空闲 = 该道 ComfyUI /queue 空 且 API (:8800/api/jobs) 没有该卡（或未分卡）的 queued/running 任务。"""
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"D:\NS-Final Studio")
sys.path[:0] = [str(ROOT / "services" / "render_router"), str(ROOT / "services" / "agent"),
                str(ROOT / "packages" / "schema"), str(ROOT / "services" / "post")]
AB = ROOT / "data" / "ab"
LOG = AB / "XP_log.md"
API = "http://127.0.0.1:8800"
ACTIVE = {"queued", "running", "pending", "starting", "submitted", "waiting"}
GPU33 = {"0": "http://127.0.0.1:18188", "1": "http://127.0.0.1:18189", "3": "http://127.0.0.1:18191"}
_log_lock = threading.Lock()


def get_json(url, timeout=30):
    return json.loads(urllib.request.urlopen(url, timeout=timeout).read())


def lanes() -> dict:
    """{gpu_key: url}；gpu33 三条 + render_endpoints.json 里新增的（gpu36）"""
    try:
        cfg = json.loads((ROOT / "config" / "render_endpoints.json").read_text(encoding="utf-8"))
        g = {str(k): v for k, v in (cfg.get("gpus") or {}).items()}
    except (OSError, ValueError):
        g = {}
    g.update(GPU33)
    g.pop("2", None)          # GPU2 坏卡，永不使用
    return g


def is_gpu36(key: str, url: str) -> bool:
    return url not in GPU33.values()


def api_active_gpus() -> set:
    """API 队列里在排/在跑的任务所在卡；gpu 为空 → 'any'"""
    try:
        jobs = get_json(f"{API}/api/jobs", 30)
    except Exception:  # noqa: BLE001  读不到就当全忙（P1 优先）
        return {"any"}
    out = set()
    for j in jobs if isinstance(jobs, list) else jobs.get("jobs", []):
        if str(j.get("state")) in ACTIVE:
            out.add(str(j["gpu"]) if j.get("gpu") is not None else "any")
    return out


def comfy_idle(url: str) -> bool:
    try:
        q = get_json(f"{url}/queue", 20)
    except Exception:  # noqa: BLE001
        return False
    return not q.get("queue_running") and not q.get("queue_pending")


def lane_free(key: str, url: str) -> bool:
    if (AB / f"lane_block_{key}").exists():      # 借出的卡（如 GPU1 训练 LoRA）：不提交
        return False
    act = api_active_gpus()
    if "any" in act or key in act:
        return False
    return comfy_idle(url)


def exec_seconds(entry: dict) -> float | None:
    """history 里 execution_start → execution_success 的毫秒时间戳差（纯算力时间，不含排队）"""
    ts = {m[0]: m[1].get("timestamp") for m in (entry.get("status") or {}).get("messages", []) if isinstance(m[1], dict)}
    if ts.get("execution_start") and ts.get("execution_success"):
        return round((ts["execution_success"] - ts["execution_start"]) / 1000, 1)
    return None


def log(experiment: str, lane: str, start: float, end: float, outputs, note: str = ""):
    with _log_lock:
        new = not LOG.exists()
        with LOG.open("a", encoding="utf-8") as f:
            if new:
                f.write("# P2 画质实验日志（最低优先级，只用空闲卡）\n\n"
                        "| 实验 | 道 | 开始 | 结束 | 秒 | 输出 | 备注 |\n|---|---|---|---|---|---|---|\n")
            fmt = lambda t: time.strftime("%m-%d %H:%M:%S", time.localtime(t))
            outs = "<br>".join(str(Path(o).relative_to(ROOT)) if str(o).startswith(str(ROOT)) else str(o)
                               for o in (outputs if isinstance(outputs, (list, tuple)) else [outputs]))
            f.write(f"| {experiment} | {lane} | {fmt(start)} | {fmt(end)} | {end - start:.0f} | {outs} | {note} |\n")


def font(sz):
    from PIL import ImageFont
    for f in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except OSError:
            pass
    return ImageFont.load_default()


def wrap(draw, text, fnt, width):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
        elif draw.textlength(cur + ch, font=fnt) > width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    return lines + [cur] if cur else lines


def sheet(tiles, path, tile_w, tile_h, cols=4, label_h=150, max_lines=6, title=None):
    """tiles = [(PIL.Image, 标记, 说明文字)]"""
    from PIL import Image, ImageDraw
    rows = (len(tiles) + cols - 1) // cols
    pad, top = 8, (50 if title else 0)
    W_, H_ = cols * (tile_w + pad) + pad, top + rows * (tile_h + label_h + pad) + pad
    img = Image.new("RGB", (W_, H_), (24, 24, 24))
    dr = ImageDraw.Draw(img)
    f1, f2 = font(28), font(16)
    if title:
        dr.text((pad, 10), title, fill=(255, 255, 255), font=font(24))
    for i, (im, letter, text) in enumerate(tiles):
        x = pad + (i % cols) * (tile_w + pad)
        y = top + pad + (i // cols) * (tile_h + label_h + pad)
        img.paste(im.resize((tile_w, tile_h), Image.LANCZOS) if im.size != (tile_w, tile_h) else im, (x, y + label_h))
        dr.text((x + 4, y + 2), letter, fill=(255, 220, 80), font=f1)
        for j, ln in enumerate(wrap(dr, text, f2, tile_w - 60)[:max_lines]):
            dr.text((x + 56, y + 4 + j * 22), ln, fill=(235, 235, 235), font=f2)
    img.save(path, quality=93)
    return path
