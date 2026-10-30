"""
读 gpu3 渲染目录（只读，从不写）。两种布局：

takes（renders_gpu3，与 ns_render.pipeline 相同的 take 布局；Take.file 相对 data/）:
    <data>/renders_gpu3/epXX/SN/takes.json            {"takes":[Take…], "active":{"image":n,"video":n}}
    <data>/renders_gpu3/epXX/SN/takes/image_003.png, video_002.mp4, video_002_last.png
    <data>/renders_gpu3/epXX/SN/frame.png / video.mp4 / last.png   当前选用版本的副本
    <data>/renders_gpu3/epXX/SN/status.json / errors.json        可选
    没有 takes.json 时，把 frame.png / video.mp4 当作第 1 版（兼容 render_batch 的旧布局）。
weita（gpu3 微型测试 ns-studio/data/run/weita，只读对照）:
    epXX/frames/epXXsN.png、epXXsN.last.png（目标尾帧）、manifest.jsonl（锁定候选的种子与分数）
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .config import RootCfg
from .models import QCVerdict, TakeOut


def load_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def read_jsonl(p: Path) -> list[dict]:
    out = []
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def parse_shot_id(sid: str) -> tuple[int, int]:
    m = re.fullmatch(r"ep(\d+)[-_]?s(\d+)", sid.strip().lower())
    if not m:
        raise KeyError(sid)
    return int(m.group(1)), int(m.group(2))


def shot_id(ep: int, s: int) -> str:
    return f"ep{ep:02d}-S{s}"


QC_KEYS = {"face": "face_eyes", "face_eyes": "face_eyes", "eyes": "face_eyes", "text": "text",
           "drift": "drift", "decoration": "decoration", "decor": "decoration", "frame": "frame"}


def parse_qc(qc) -> list[QCVerdict]:
    """容错解析渲染器写的 qc。见过的形状（weita_series）：
    {"face":{"verdict":"warn","score":0.9,"reasons":[…]},                   带 verdict 的检查
     "decoration":{"clothed":{"ok":true,"answer":"…"}} / {"heels":"透明高跟 true"},  无 verdict：按子项 ok 推断
     "drift":{"first_frame_psnr":33.4,"end_identity":0.09},                    指标：verdict=unknown，原样列出
     "fail":["QC: …"], "override":"人工复核说明"}                              汇总失败列表 / 备注
    也接受 [{"check":…,"verdict":…}] 和 "pass" 这种简写。"""
    if isinstance(qc, list):
        items = [(q.get("check", "frame"), q) for q in qc if isinstance(q, dict)]
    elif isinstance(qc, dict):
        items = list(qc.items())
    else:
        return []
    short = lambda x: (json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x)[:200]
    out = []
    for k, v in items:
        check = QC_KEYS.get(k, k)
        if isinstance(v, list):
            if v:
                out.append(QCVerdict(check=check, verdict="fail", reasons=[short(x) for x in v][:6]))
            continue
        if isinstance(v, str):
            verdict = v if v in ("pass", "warn", "fail") else "unknown"
            out.append(QCVerdict(check=check, verdict=verdict, reasons=[] if verdict != "unknown" else [short(v)]))
            continue
        if not isinstance(v, dict):
            out.append(QCVerdict(check=check, reasons=[short(v)]))
            continue
        verdict = v.get("verdict")
        reasons = v.get("reasons")
        if verdict not in ("pass", "warn", "fail"):
            oks = [x.get("ok") for x in v.values() if isinstance(x, dict) and "ok" in x]
            verdict = "fail" if False in oks else "pass" if oks and all(oks) else "unknown"
            if reasons is None:
                reasons = [f"{kk}={short(vv)}" for kk, vv in v.items() if kk not in ("score", "verdict")]
        score = v.get("score")
        out.append(QCVerdict(check=check, verdict=verdict, reasons=[short(r) for r in (reasons or [])][:6],
                             score=score if isinstance(score, (int, float)) else None))
    return out


Found = list[tuple[TakeOut, dict[str, Path]]]   # take + 绝对路径 {"file","last_frame","last_target"}


class Root:
    def __init__(self, cfg: RootCfg):
        self.cfg = cfg

    @property
    def label(self) -> str:
        return self.cfg.label

    def takes(self, ep: int, s: int) -> tuple[Found, dict, str | None]:
        """返回 (takes, active, error)。"""
        raise NotImplementedError

    def shot_numbers(self, ep: int) -> list[int]:
        return []


class TakesRoot(Root):
    @property
    def data_dir(self) -> Path:
        return self.cfg.data_dir or self.cfg.path.parent

    def shot_dir(self, ep, s) -> Path:
        return self.cfg.path / f"ep{ep:02d}" / f"S{s}"

    def shot_numbers(self, ep):
        d = self.cfg.path / f"ep{ep:02d}"
        return sorted(int(x.name[1:]) for x in d.glob("S*") if x.is_dir() and x.name[1:].isdigit()) if d.is_dir() else []

    def takes(self, ep, s):
        d = self.shot_dir(ep, s)
        if not d.is_dir():
            return [], {}, None
        st = load_json(d / "status.json", {}) or {}
        err = load_json(d / "errors.json", None)
        error = (err.get("last") if isinstance(err, dict) else None) or None
        data = load_json(d / "takes.json")
        found: Found = []
        if data and data.get("takes"):
            active = data.get("active", {}) or {}
            for t in data["takes"]:
                paths = {}
                for key, rel in (("file", t.get("file")), ("last_frame", t.get("last_frame"))):
                    if rel:
                        p = self.data_dir / rel
                        if p.exists():
                            paths[key] = p
                if t.get("last_target"):
                    p = self.data_dir / t["last_target"]
                    if p.exists():
                        paths["last_target"] = p
                found.append((TakeOut(source=self.label, stage=t["stage"], n=t["n"], active=active.get(t["stage"]) == t["n"],
                                      file=t.get("file"), seed=t.get("seed"), prompt=t.get("prompt"), seconds=t.get("seconds"),
                                      frames=t.get("frames"), created_at=t.get("created_at"), workflow=t.get("workflow"),
                                      request_id=t.get("request_id"), input_hash=t.get("input_hash"),
                                      qc=parse_qc(t.get("qc"))), paths))
            return found, {k: active.get(k) for k in ("image", "video")}, error
        # 旧布局：frame.png / video.mp4 视为第 1 版
        im, vi = st.get("image", {}) or {}, st.get("video", {}) or {}
        rel = lambda p: p.relative_to(self.data_dir).as_posix()
        if (d / "frame.png").exists():
            found.append((TakeOut(source=self.label, stage="image", n=1, active=True, file=rel(d / "frame.png"),
                                  seed=im.get("seed"), seconds=im.get("seconds"), qc=parse_qc(st.get("qc"))),
                          {"file": d / "frame.png"}))
        if (d / "video.mp4").exists():
            paths = {"file": d / "video.mp4"}
            if (d / "last.png").exists():
                paths["last_frame"] = d / "last.png"
            found.append((TakeOut(source=self.label, stage="video", n=1, active=True, file=rel(d / "video.mp4"),
                                  seed=vi.get("seed"), seconds=vi.get("seconds"), frames=vi.get("frames")), paths))
        if not error:
            for k, v in (("首帧", im), ("视频", vi)):
                if v.get("ok") is False:
                    error = f"{k}: {v.get('error', '')}"
        return found, {"image": 1 if any(t.stage == "image" for t, _ in found) else None,
                       "video": 1 if any(t.stage == "video" for t, _ in found) else None}, error


class WeitaRoot(Root):
    def _manifest(self) -> list[dict]:
        p = self.cfg.path / "manifest.jsonl"
        try:
            return _manifest_cached(str(p), p.stat().st_mtime)
        except OSError:
            return []

    def shot_numbers(self, ep):
        d = self.cfg.path / f"ep{ep:02d}" / "frames"
        pat = re.compile(rf"ep{ep:02d}s(\d+)\.png$")
        return sorted({int(m.group(1)) for p in d.glob("*.png") if (m := pat.match(p.name))}) if d.is_dir() else []

    def takes(self, ep, s):
        sid = f"ep{ep:02d}s{s}"
        epd = self.cfg.path / f"ep{ep:02d}"
        found: Found = []
        frame, last = epd / "frames" / f"{sid}.png", epd / "frames" / f"{sid}.last.png"
        man = [r for r in self._manifest() if r.get("shot_id") == sid]
        locked = next((r for r in reversed(man) if r.get("kind") == "frame_locked"), None)
        scores = next((r for r in reversed(man) if r.get("kind") == "frame_scores"), None)
        if frame.exists():
            t = TakeOut(source=self.label, stage="image", n=1, seed=(locked or {}).get("seed"),
                        created_at=(locked or {}).get("at"), workflow="weita")
            sc = ((scores or {}).get("scores") or {}).get(f"{sid}_{(locked or {}).get('candidate')}")
            if sc:
                t.qc.append(QCVerdict(check="face_eyes", verdict=sc["qc"] if sc.get("qc") in ("pass", "warn", "fail") else "unknown",
                                      reasons=sc.get("qc_reasons", []), score=sc.get("similarity")))
            paths = {"file": frame}
            if last.exists():
                paths["last_target"] = last
            found.append((t, paths))
        vids = [p for p in epd.rglob(f"{sid}*.mp4") if "cand" not in p.parts] if epd.is_dir() else []
        for i, v in enumerate(sorted(vids, key=lambda p: p.stat().st_mtime), 1):
            found.append((TakeOut(source=self.label, stage="video", n=i, workflow=v.parent.parent.name), {"file": v}))
        return found, {}, None


@lru_cache(maxsize=8)
def _manifest_cached(path: str, mtime: float) -> list[dict]:
    return read_jsonl(Path(path))


def make_roots(cfgs: list[RootCfg]) -> list[Root]:
    kinds = {"takes": TakesRoot, "nsfs": TakesRoot, "weita": WeitaRoot}
    return [kinds[c.kind](c) for c in cfgs if c.kind in kinds]
