"""fredw-92/PF：Pika H3 Flex A/B（项目方挑，不评判）。只写 data/ab/pika_flex/，不建 take、不动生产数据。

用法：
  python tools/ab/pika_flex_ab.py render --lane 0 ep02-S2 ep02-S5   # 同种子、同首尾帧、同提示词、同帧数，基底 pika_flex
  python tools/ab/pika_flex_ab.py compare ep02-S2 ep02-S5           # 并排 mp4 + 帧对比图 + 首尾帧贴合（PSNR/SSIM）+ params.md
官方 = 该镜当前视频版本（active video take）；Flex = 本脚本渲染。道须空闲（API 无该卡任务且 ComfyUI /queue 空）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import xp_common as X  # noqa: E402
import numpy as np  # noqa: E402
from ns_render import h3_video as HV  # noqa: E402
from ns_render import pipeline as P  # noqa: E402
from ns_render.comfy_client import ComfyClient  # noqa: E402

OUT = X.AB / "pika_flex"
BASE = "pika_flex"


def shot_paths(shot: str) -> tuple[Path, str]:
    ep, sn = shot.split("-")
    return OUT / shot, f"{ep}/{sn}"


def active_video(shot: str) -> dict:
    tk = P.load_takes(shot)
    n = tk.get("active", {}).get("video")
    t = next(t for t in tk["takes"] if t["stage"] == "video" and t["n"] == n)
    lf = HV.locked_frames(shot)
    p = t.get("params") or {}
    for k in ("first", "last"):
        if p.get(k) and p[k].get("sha") != lf[k]["sha"]:
            raise SystemExit(f"{shot} 当前视频 #{n} 的{k}帧不是当前定稿（{p[k]} vs {lf[k]}）")
    return t


def wait_lane(pref: str, max_wait_s: float = 4 * 3600) -> tuple[str, str]:
    """等一条空闲道：连续两次（间隔 60 s）都空闲才用（避免插进别人两次提交之间）。pref="auto" = 任意道"""
    t0 = time.time()
    while time.time() - t0 < max_wait_s:
        ls = X.lanes()
        # pref："auto" = 任意道（GPU1 今晚借给训练，auto 不用）；"0,3" = 只在这几条里挑
        keys = [k for k in ls if k != "1"] if pref == "auto" else [k for k in pref.split(",") if k in ls]
        for k in keys:
            if X.lane_free(k, ls[k]):
                time.sleep(60)
                if X.lane_free(k, ls[k]):
                    return k, ls[k]
        time.sleep(30)
    raise SystemExit(f"等了 {max_wait_s:.0f} s 没有空闲道")


def render(shots: list[str], pref: str):
    OUT.mkdir(parents=True, exist_ok=True)
    for shot in shots:
        lane, url = wait_lane(pref)
        print(shot, "lane", lane, url, flush=True)
        t = active_video(shot)
        d, _ = shot_paths(shot)
        d.mkdir(parents=True, exist_ok=True)
        p = t["params"]
        client = ComfyClient(url, timeout=120, gpu=int(lane) if lane.isdigit() else None)
        spec = HV.base_spec(BASE)
        if spec["lora"] not in P.available_loras(client):
            raise SystemExit(f"道 {lane} 没有 {spec['lora']}")
        t_up = time.monotonic()
        first = HV.upload_once(client, P.DATA / p["first"]["file"])
        last = HV.upload_once(client, P.DATA / p["last"]["file"])
        upload_s = round(time.monotonic() - t_up, 1)
        wf = HV.build(t["prompt"], first, last, int(t["frames"]), int(t["seed"]), f"ns_ab/pika_flex/{shot}", base=BASE)
        probs = client.check(wf)
        if probs:
            raise SystemExit("工作流检查不通过：" + "；".join(probs))
        (d / "workflow_flex.json").write_text(json.dumps(wf, ensure_ascii=False, indent=1), encoding="utf-8")
        start = time.time()
        t0 = time.monotonic()
        with HV.VramSampler(client) as vram:
            pid = client.submit(wf)
            print(shot, "submitted", pid, flush=True)
            entry = client.wait(pid, 3600)
        wall = round(time.monotonic() - t0, 1)
        item = next(f for f in client.output_files(entry) if f["filename"].endswith(".mp4"))
        client.download(item, d / "flex.mp4")
        shutil.copy2(P.DATA / t["file"], d / "official.mp4")
        rec = {"shot": shot, "lane": lane, "url": url, "prompt_id": pid, "wall_s": wall, "exec_s": X.exec_seconds(entry),
               "upload_s": upload_s, "vram_peak_gb": vram.peak, "vram_total_gb": vram.total,
               "seed": int(t["seed"]), "frames": int(t["frames"]), "official_take": t["n"], "official_file": t["file"],
               "official_render_s": p.get("render_s") or t.get("seconds"), "official_gpu": t.get("gpu"),
               "official_vram_peak_gb": p.get("vram_peak_gb"),
               "first": p["first"], "last": p["last"], "base": HV.base_spec(BASE), "prompt": t["prompt"]}
        (d / "flex_run.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        X.log("PF Pika Flex A/B", f"gpu{lane}", start, time.time(), [d / "flex.mp4"], f"{shot} seed {t['seed']} {t['frames']}f")
        print(shot, "done", wall, "s", "vram", vram.peak, flush=True)


# ---------------------------------------------------------------- 对比

def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)


def nframes(mp4: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=nb_read_frames", "-of", "csv=p=0", str(mp4)], capture_output=True, text=True)
    return int(out.stdout.strip().split(",")[0])


def frame(mp4: Path, i: int, out: Path) -> Path:
    ff("-i", mp4, "-vf", f"select='eq(n\\,{i})'", "-fps_mode", "passthrough", "-frames:v", "1", out)
    return out


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    """灰度 SSIM（Wang 2004，11×11 高斯 σ1.5，K1 0.01 K2 0.03）"""
    import cv2
    a = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY).astype(np.float64)
    b = cv2.cvtColor(b, cv2.COLOR_RGB2GRAY).astype(np.float64)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    g = lambda x: cv2.GaussianBlur(x, (11, 11), 1.5)
    ma, mb = g(a), g(b)
    va, vb, cab = g(a * a) - ma ** 2, g(b * b) - mb ** 2, g(a * b) - ma * mb
    m = ((2 * ma * mb + C1) * (2 * cab + C2)) / ((ma ** 2 + mb ** 2 + C1) * (va + vb + C2))
    return round(float(m.mean()), 4)


def psnr(a, b) -> float:
    mse = float(((a.astype(np.float32) - b.astype(np.float32)) ** 2).mean())
    return round(10 * np.log10(255 ** 2 / mse), 2) if mse > 0 else 99.0


def compare(shots: list[str]):
    from PIL import Image, ImageDraw
    summary = []
    for shot in shots:
        d, _ = shot_paths(shot)
        run = json.loads((d / "flex_run.json").read_text(encoding="utf-8"))
        vids = {"official": d / "official.mp4", "flex": d / "flex.mp4"}
        lab = {"official": "A 官方 8 步（当前）", "flex": "B Pika H3 Flex（6 步）"}
        tmp = d / "_frames"
        tmp.mkdir(exist_ok=True)
        # 并排 mp4（左 官方 / 右 Flex，标签英文避免字体转义；音轨用左边）
        font = "C\\:/Windows/Fonts/arial.ttf"
        dt = lambda s: (f"drawtext=fontfile='{font}':text='{s}':x=20:y=20:fontsize=40:fontcolor=white:"
                        "box=1:boxcolor=black@0.6:boxborderw=10")
        ff("-i", vids["official"], "-i", vids["flex"], "-filter_complex",
           f"[0:v]scale=768:1344,{dt('A  official turbo 8-step (current)')}[a];"
           f"[1:v]scale=768:1344,{dt('B  Pika H3 Flex 6-step')}[b];[a][b]hstack=inputs=2[v]",
           "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
           "-shortest", d / f"{shot}_sidebyside.mp4")
        # 帧对比图：0/25/50/75/100 %
        n = {k: nframes(v) for k, v in vids.items()}
        tiles = []
        for k in ("official", "flex"):
            for pct in (0, 25, 50, 75, 100):
                i = min(n[k] - 1, round((n[k] - 1) * pct / 100))
                im = Image.open(frame(vids[k], i, tmp / f"{k}_{pct}.png")).convert("RGB")
                tiles.append((im, "A" if k == "official" else "B", f"{lab[k]} · {pct}%（第 {i} 帧）"))
        X.sheet(tiles, d / f"{shot}_frames_0-25-50-75-100.jpg", 288, 504, cols=5, label_h=60, max_lines=2,
                title=f"{shot} · 上排 A 官方 8 步（当前 #{run['official_take']}）/ 下排 B Pika H3 Flex · 种子 {run['seed']} · {run['frames']} 帧")
        # 首尾帧贴合：视频第 0 帧 vs 定稿首帧、最后一帧 vs 定稿尾帧（定稿图按出视频同样 center-crop+lanczos 到 768×1344）
        locks = {"first": np.asarray(Image.open(HV.keyframe_file(P.DATA / run["first"]["file"])).convert("RGB")),
                 "last": np.asarray(Image.open(HV.keyframe_file(P.DATA / run["last"]["file"])).convert("RGB"))}
        metrics, ktiles = {}, []
        for k in ("official", "flex"):
            metrics[k] = {}
            for end, idx in (("first", 0), ("last", n[k] - 1)):
                im = Image.open(frame(vids[k], idx, tmp / f"{k}_{end}.png")).convert("RGB")
                a = np.asarray(im.resize((768, 1344), Image.LANCZOS) if im.size != (768, 1344) else im)
                metrics[k][end] = {"frame": idx, "psnr_db": psnr(a, locks[end]), "ssim": ssim(a, locks[end])}
        for end, nm in (("first", "首帧"), ("last", "尾帧")):
            ktiles.append((Image.fromarray(locks[end]), "锁", f"定稿{nm}（{run[end]['file'].split('/')[-1]}）"))
            for k in ("official", "flex"):
                m = metrics[k][end]
                ktiles.append((Image.open(tmp / f"{k}_{end}.png").convert("RGB"), "A" if k == "official" else "B",
                               f"{lab[k]} 第 {m['frame']} 帧 · PSNR {m['psnr_db']} dB · SSIM {m['ssim']}"))
        X.sheet(ktiles, d / f"{shot}_keyframe_fit.jpg", 288, 504, cols=3, label_h=80, max_lines=3,
                title=f"{shot} · 首尾帧贴合（和定稿关键帧比；越高越贴）")
        summary.append({"shot": shot, "frames": n, "metrics": metrics, "run": run})
        (d / "metrics.json").write_text(json.dumps({"frames": n, "metrics": metrics}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    write_params(summary)


def write_params(summary):
    f = HV.base_spec(BASE)
    o = HV.base_spec("official_turbo")
    L = ["# Pika H3 Flex A/B（fredw-92/PF，2026-10-31）", "",
         "项目方原话：“Pika H3 Flex 下载体验一下，画面可以选择基底”。**由项目方挑，这里不评判。** 非生产版本（不进 takes.json）。", "",
         "## 两个基底的参数", "",
         "| | A 官方 8 步（当前） | B Pika H3 Flex |", "|---|---|---|",
         f"| 底模 | minimax_h3_fl2va_pruned_int8_convrot | 同左 |",
         f"| LoRA | `{o['lora']}` @{o['lora_strength']} | `{f['lora']}` @{f['lora_strength']}（不叠 Turbo） |",
         f"| 采样 | {o['sampler']} / {o['scheduler']}，{o['steps']} 步 | {f['sampler']}，ManualSigmas `{f['sigmas']}`（{f['steps']} 步） |",
         f"| shift | MiniMaxH3SigmaShift {o['shift'][0]:g}/{o['shift'][1]:g} | {f['shift'][0]:g}/{f['shift'][1]:g}（已算进 sigma 表，无 SigmaShift 节点，同官方模板） |",
         "| CFG / guider | 1.0 / BasicGuider | 1.0 / BasicGuider |",
         "| 首尾帧 / 提示词 / 种子 / 帧数 / 分辨率 | 当前定稿首尾帧、当前视频版本的提示词原文 | 完全相同；768×1344、24 fps |", "",
         f"- Flex 来源：{f['source_url']}（sha256 `{f['sha256']}`，与官方 SHA256SUMS 一致）",
         f"- 官方模板：{f['template_url']}；文档：{f['docs_url']}",
         f"- 许可：{f['license']}",
         f"- 注意：{f['caveats']}", "",
         "## 结果", "",
         "| 镜头 | 种子 | 帧数 | A 耗时（生产记录） | B 耗时（本次） | B 显存峰值 | 首帧 PSNR/SSIM A → B | 尾帧 PSNR/SSIM A → B |",
         "|---|---|---|---|---|---|---|---|"]
    for s in summary:
        r, m = s["run"], s["metrics"]
        fm = lambda k, e: f"{m[k][e]['psnr_db']} dB / {m[k][e]['ssim']}"
        L.append(f"| {s['shot']} | {r['seed']} | {r['frames']} | {r['official_render_s']} s（GPU{r['official_gpu']}，"
                 f"#{r['official_take']}） | {r['wall_s']} s（GPU{r['lane']}，执行 {r['exec_s']} s） | "
                 f"{r['vram_peak_gb']} / {r['vram_total_gb']} GB | {fm('official', 'first')} → {fm('flex', 'first')} | "
                 f"{fm('official', 'last')} → {fm('flex', 'last')} |")
    L += ["", "- 耗时：A 是该版本生产渲染时记的 render_s（当时那条道可能有排队 / 共享），B 是本次空闲 GPU0 实测，含模型加载"
          "（GPU0 ComfyUI 是 --cache-none，每次重载底模），**不能直接当速度比**。",
          "- 首尾帧贴合：视频第 0 帧 / 最后一帧 vs 定稿关键帧（按出视频的同一 center-crop + lanczos 到 768×1344），"
          "PSNR（dB）和灰度 SSIM 越高越贴。", "",
          "## 文件（每镜一个子目录）", "",
          "- `<镜头>_sidebyside.mp4`：左 A 官方 / 右 B Flex（音轨取 A）",
          "- `<镜头>_frames_0-25-50-75-100.jpg`：上排 A、下排 B",
          "- `<镜头>_keyframe_fit.jpg`：定稿首/尾帧 vs 两边的第 0 帧 / 最后一帧",
          "- `official.mp4`、`flex.mp4`、`flex_run.json`（含提示词、全部参数、计时）、`workflow_flex.json`、`metrics.json`", ""]
    (OUT / "params.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:]
    if cmd == "render":
        lane = "auto"
        if rest and rest[0] == "--lane":
            lane, rest = rest[1], rest[2:]
        render(rest, lane)
    elif cmd == "compare":
        compare(rest)
    else:
        raise SystemExit(__doc__)
