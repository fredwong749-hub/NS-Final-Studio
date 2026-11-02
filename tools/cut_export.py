"""CUTEDIT：剪辑工程 → 定稿成片（服务端合成，只用 CPU）。由 POST /api/episodes/{n}/cut-project/export 起的子进程跑。

    .venv/Scripts/python.exe tools/cut_export.py ep01 [--rev 3]

读 data/renders/epNN/_final/cut_project.json：镜头段钉住工程里的源文件（sources），项目方动过的入出点走
assemble_episode(cut_edit=...)（手动优先于自动裁切），配乐换曲 / 起点 / 音量 / 淡入淡出同样走 cut_edit；
后期链和 tools/assemble_series.py 成片版同一套（配音 TTS 缓存 / H3 原声、集级 BGM、-14 LUFS、不烧字幕 + 外挂 srt）。
产物：_final/epNN_cut_r<rev>.mp4 + .timeline.json + .srt + _manifest.json；完成后写进工程 final（= 本集定稿版本）。
进度写 _final/_cut_export_job.json（收下 → 合成画面 → 混音 + 响度 → 定稿），界面原位显示。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("NS_PROJECT_ROOT") or CODE)   # 和 ns_render.pipeline 同一约定（沙盒 / projects/<slug>）
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / "services" / "post"))
sys.path.insert(0, str(CODE / "services" / "api"))
sys.path.insert(0, str(CODE / "services" / "render_router"))


def read_json(p: Path, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def sources_of(proj: dict) -> dict[int, dict]:
    out = {}
    for s in proj["segments"]:
        p = ROOT / s["file"] if s.get("file") else None
        if s.get("kind") == "video" and p and p.is_file():
            out[int(s["index"])] = {"kind": "video", "origin": s.get("origin"), "path": p, "path_4k": None}
        elif s.get("kind") == "still" and p and p.is_file():
            out[int(s["index"])] = {"kind": "still", "origin": s.get("origin"), "path": p, "placeholder": True}
        else:
            out[int(s["index"])] = {"kind": "black", "origin": None, "path": None, "missing": True,
                                    "missing_reason": "工程里这一镜没有可用文件"}
    return out


class Progress:
    """阶段：picture（合成画面）→ sound（混音 + 响度，看工作目录出现 picture.mp4）→ final（出现 mix.wav 之后 / 收尾）"""

    def __init__(self, job_p: Path, work_root: Path, prefix: str):
        self.job_p, self.work_root, self.prefix = job_p, work_root, prefix
        self.t0 = time.time()
        self.stop = threading.Event()
        self.before = set(self._dirs())   # 开工前已有的工作目录；本次装配的 = 之后新冒出来的那个（不按修改时间猜）

    def set(self, **kw) -> None:
        j = read_json(self.job_p, {}) or {}
        j.update(kw)
        write_json(self.job_p, j)

    def _dirs(self) -> list[Path]:
        return [d for d in self.work_root.glob(f"{self.prefix}_*") if d.is_dir()] if self.work_root.is_dir() else []

    def _work(self) -> Path | None:
        new = [d for d in self._dirs() if d not in self.before]
        return new[0] if len(new) == 1 else None   # 同时冒出多个（别的装配也在跑）→ 不认，进度按时间估

    def run(self) -> None:
        stage = "picture"
        while not self.stop.wait(3):
            w = self._work()
            if w and (w / "mix.wav").exists() and stage != "final":
                stage = "final"
                self.set(state="final", stage="定稿", pct=90)
            elif w and (w / "picture.mp4").exists() and stage == "picture":
                stage = "sound"
                self.set(state="sound", stage="混音 + 响度", pct=60)
            elif stage == "picture":
                j = read_json(self.job_p, {}) or {}
                el = time.time() - self.t0
                self.set(pct=min(55, 8 + int(47 * el / max(30.0, 0.6 * float(j.get("est_s") or 180)))))


def main(argv=None) -> int:
    for st in (sys.stdout, sys.stderr):   # 子进程输出重定向到日志文件时默认 cp1252，中文警告会崩
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("episode")
    ap.add_argument("--rev", type=int, default=None)
    a = ap.parse_args(argv)
    ep = int(a.episode.lower().removeprefix("ep"))
    name = f"ep{ep:02d}"
    fin = ROOT / "data" / "renders" / name / "_final"
    proj_p, job_p = fin / "cut_project.json", fin / "_cut_export_job.json"
    proj = read_json(proj_p)
    if not proj:
        write_json(job_p, (read_json(job_p, {}) or {}) | {"state": "failed", "error": "没有剪辑工程"})
        return 2
    rev = int(proj["rev"])
    from ns_api.cut_project import cut_edit_of  # noqa: E402
    from ns_post.assemble import Settings, assemble_episode, load_episode  # noqa: E402
    from ns_post.tts import KokoroBackend, SenseVoiceAsr, load_voice_config  # noqa: E402

    work = fin / "_asm"
    work.mkdir(parents=True, exist_ok=True)
    cache_dir = ROOT / "data/cache/tts"
    prog = Progress(job_p, cache_dir.parent / "post", name)
    prog.set(state="picture", stage="合成画面", pct=8, rev=rev, error=None, output=None)
    th = threading.Thread(target=prog.run, daemon=True)
    th.start()
    t0 = time.time()
    try:
        cfg = load_voice_config()
        variant = f"cut_r{rev}"
        settings = Settings(threads=8, bgm=True, deliver_4k="off", dialogue_source=proj.get("dialogue_source") or "h3",
                            music_dir=str(ROOT / "data/music/series10"))
        episode = load_episode(ROOT / "data/import/script_v2.json", ep)
        cut_edit = cut_edit_of(proj)
        tl = assemble_episode(episode, work, tts=KokoroBackend(cfg, num_threads=4), cache_dir=cache_dir,
                              asr=SenseVoiceAsr(cfg, num_threads=4), settings=settings, voices_cfg=cfg,
                              allow_laptop_video=False, keep_work=False, sources=sources_of(proj), variant=variant,
                              cut_edit=cut_edit)
        prog.stop.set()
        produced = ROOT / next(iter(tl["deliveries"].values()))["file"]
        base = f"{name}_{variant}"
        final = fin / f"{base}.mp4"
        shutil.copyfile(produced, final.with_suffix(".mp4.tmp"))
        os.replace(final.with_suffix(".mp4.tmp"), final)
        tlj = next(iter(work.glob(f"*{variant}.timeline.json")), None)
        if tlj:
            shutil.copyfile(tlj, fin / f"{base}.timeline.json")
        cues = sorted((s for s in tl["speech"] if s.get("start_s") is not None), key=lambda s: s["start_s"])
        srt = "\n".join(f"{i}\n{srt_time(s['start_s'])} --> {srt_time(s['end_s'])}\n{s['text']}\n" for i, s in enumerate(cues, 1))
        (fin / f"{base}.srt").write_text(srt, encoding="utf-8")
        rel = str(final.relative_to(ROOT)).replace("\\", "/")
        build_s = round(time.time() - t0, 1)
        write_json(fin / f"{base}_manifest.json", {
            "episode": name, "variant": variant, "cut_project_rev": rev, "output": rel,
            "srt": str((fin / f"{base}.srt").relative_to(ROOT)).replace("\\", "/"), "duration_s": tl["duration_s"],
            "cut_edit": cut_edit, "bgm": tl["bgm"].get("file") or tl["bgm"].get("reason"),
            "loudness": tl["loudness"]["measured"], "subtitles": "sidecar .srt（不烧录，L-002）",
            "warnings": tl["warnings"], "built_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"), "build_s": build_s})
        cur = read_json(proj_p, proj) or proj   # 导出期间工程可能又被改过：只写 final，不动别的
        cur["final"] = {"file": rel, "rev": rev, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "build_s": build_s,
                        "duration_s": tl["duration_s"]}
        cur["history"] = (cur.get("history") or [])[-49:] + [{"at": cur["final"]["at"], "what": f"导出定稿 {final.name}", "by": "system"}]
        write_json(proj_p, cur)
        prog.set(state="done", stage="定稿", pct=100, output=rel, finished_at=cur["final"]["at"], build_s=build_s)
        print(f"OK {rel} {tl['duration_s']}s in {build_s}s")
        return 0
    except Exception as e:  # noqa: BLE001
        prog.stop.set()
        traceback.print_exc()
        prog.set(state="failed", error=f"{type(e).__name__}: {str(e)[:300]}", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
