"""调本地看图服务（gpu36 tools/vqa/server.py）。只走自家机器：本机 127.0.0.1:8870（在 gpu36 上跑时）或 `ssh gpu36` 管道。
绝不把图片发到任何外部地址（K-REV-V01）：URL 只允许 127.0.0.1 / localhost，远端只允许 config model.host。"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import ROOT, cfg, rubric

CACHE = ROOT / "data" / "vqa" / "verdicts"
LOCAL_HOSTS = ("127.0.0.1", "localhost")


def _url() -> str:
    m = cfg().get("model") or {}
    u = os.environ.get("VQA_URL") or f"http://127.0.0.1:{m.get('port', 8870)}"
    host = u.split("//", 1)[-1].split(":", 1)[0].split("/", 1)[0]
    if host not in LOCAL_HOSTS:
        raise ValueError(f"K-REV-V01：看图服务只能是本机地址，拒绝 {u}")
    return u


def _key(req: dict) -> str:
    h = hashlib.sha256()
    h.update((cfg().get("version", "") + req.get("system", "") + req["text"]).encode("utf-8"))
    for im in req["images"]:
        p = Path(im["path"])
        h.update(p.read_bytes() if p.exists() else im["path"].encode())
        h.update(str(im.get("max_pixels")).encode())
    return h.hexdigest()[:24]


def _local_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/health", timeout=3):
            return True
    except (OSError, urllib.error.URLError):
        return False


def _post_local(url: str, body: dict, timeout: float) -> dict:
    r = urllib.request.Request(url + "/generate", data=json.dumps(body).encode("utf-8"),
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}") or {"error": f"HTTP {e.code}"}


def _shrink(p: Path, max_pixels) -> bytes:
    """VQAGATE 11-01：笔记本上行慢（K-OPS-302），原图 PNG 2–4 MB × 5 张走 ssh 一张要几分钟。服务端本来就按 max_pixels 缩，
    这里先在本机缩到 max_pixels 再转 JPEG q92 发（缓存键仍按原图字节算，判定口径不变）。读不了就发原字节"""
    try:
        import io
        from PIL import Image
        with Image.open(p) as im:
            im = im.convert("RGB")
            mp = int(max_pixels or 1300000)
            if im.width * im.height > mp:
                k = (mp / (im.width * im.height)) ** 0.5
                im = im.resize((max(28, int(im.width * k)), max(28, int(im.height * k))), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=92)
            return buf.getvalue()
    except Exception:  # noqa: BLE001
        return p.read_bytes()


def _post_ssh(body: dict, timeout: float) -> dict:
    m = cfg().get("model") or {}
    host, port = m.get("host", "gpu36"), m.get("port", 8870)
    # 图片以字节随请求走 ssh 管道到自家 gpu36，服务只听 127.0.0.1
    for im in body["images"]:
        if "path" in im and Path(im["path"]).exists():
            im["b64"] = base64.b64encode(_shrink(Path(im["path"]), im.get("max_pixels"))).decode()
            im.pop("path")
    cmd = ["ssh", "-o", "BatchMode=yes", host,
           f"curl -s -m {int(timeout)} -X POST -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:{port}/generate"]
    p = subprocess.run(cmd, input=json.dumps(body).encode("utf-8"), capture_output=True, timeout=timeout + 30)
    try:
        return json.loads(p.stdout or b"{}") or {"error": (p.stderr or b"").decode("utf-8", "replace")[:300] or "空回复"}
    except ValueError:
        return {"error": (p.stdout or b"")[:300].decode("utf-8", "replace")}


def generate(req: dict, *, wait_s: float = 1800, refresh: bool = False, label: str = "") -> dict:
    """req = rubric.build_*_request(...) → {text, seconds, gpu, cached, key} 或 {error}"""
    key = _key(req)
    CACHE.mkdir(parents=True, exist_ok=True)
    cf = CACHE / f"{key}.json"
    if cf.exists() and not refresh:
        return {**json.loads(cf.read_text(encoding="utf-8")), "cached": True, "key": key}
    body = {"system": req.get("system"), "text": req["text"], "key": key, "wait_s": wait_s, "label": label,
            "max_new_tokens": int((cfg().get("model") or {}).get("max_new_tokens", 900)),
            "images": [{k: v for k, v in im.items()} for im in req["images"]], "refresh": refresh}
    url = _url()
    if not _local_up(url):
        # VQAGATE 11-01：本机服务（8870，笔记本 4080）没起时，先试常驻 ssh 隧道 127.0.0.1:8871 → gpu36:8870（tools/vqa/tunnel.ps1；
        # 一条长连接，免得每张图都走一次跳板握手），再退回单次 ssh 管道
        alt = url.rsplit(":", 1)[0] + ":" + str(int(url.rsplit(":", 1)[1].split("/")[0]) + 1)
        url = alt if _local_up(alt) else None
    res = _post_local(url, body, wait_s + 120) if url else _post_ssh(body, wait_s + 120)
    if "error" not in res:
        res["key"] = key
        cf.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res


def _finish(req: dict, res: dict, kind: str, subject: str) -> dict:
    if "error" in res:
        return {"kind": kind, "subject": subject, "error": res["error"], "checks": {}, "defects": [], "unsure": []}
    v = rubric.parse(res.get("text", ""))
    v.update(kind=kind, subject=subject, model=res.get("model"), seconds=res.get("seconds"), key=res.get("key"),
             cached=res.get("cached"), version=cfg().get("version"), at=time.strftime("%Y-%m-%dT%H:%M:%S"),
             spec=req.get("spec"))
    if not v.get("ok_parse"):
        v["error"] = "看图模型输出不是 JSON"
    return v


def inspect_image(subject: str, prompt: str, references: list[str] | None = None, **kw) -> dict:
    """出图复核：→ 规范化判定（rubric.parse 的字段 + kind / subject / model / seconds / key）"""
    req = rubric.build_image_request(subject, prompt, references, extra_refs=kw.pop("extra_refs", None),
                                     spec=kw.pop("spec", None))
    return _finish(req, generate(req, **kw), "image", str(subject))


def sample_frames(video: str | Path, n: int | None = None, out_dir: Path | None = None) -> list[str]:
    """均匀抽 n 帧（含第 1 帧，覆盖开头定格 R11-8）。用 cv2，本机算"""
    import cv2
    n = n or int((cfg().get("model") or {}).get("video_frames", 6))
    video = Path(video)
    out_dir = out_dir or (ROOT / "data" / "vqa" / "frames" / video.stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    idx = sorted({0, min(total - 1, int(fps))} | {int(i * (total - 1) / max(1, n - 1)) for i in range(n)})[:n + 1]
    out = []
    for i in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if ok:
            p = out_dir / f"f{i:05d}.jpg"
            cv2.imwrite(str(p), fr, [cv2.IMWRITE_JPEG_QUALITY, 92])
            out.append(str(p))
    cap.release()
    return out


def inspect_video(video: str | Path, prompt: str, references: list[str] | None = None, **kw) -> dict:
    frames = sample_frames(video, kw.pop("n", None))
    req = rubric.build_video_request(frames, prompt, references)
    v = _finish(req, generate(req, **kw), "video", str(video))
    v["frames"] = frames
    return v
