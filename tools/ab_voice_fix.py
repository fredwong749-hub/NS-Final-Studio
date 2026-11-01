"""
VOX（fredw-92，2026-10-31）：顾沉声音偏生硬 / S6“您”读成“你” → 换种子重出 H3 视频，出试听表。

项目方原话：“男生的声音有点生硬”“不接受 S6 念成了“明天还你””；修法三选全要（换种子 / 写作模型改声音描述 / 变声）。

  .venv/Scripts/python.exe tools/ab_voice_fix.py render [--per-shot 2] [--max-inflight 3] [--mode use|none|auto]
      经真实 API（POST /api/shots/{id}/video-jobs）给顾沉有台词的镜各出 N 版新种子；S6 一版一版出，
      SenseVoice 听到“您”就停，最多 4 版。首尾帧用定稿的，提示词用剧本原样（不传 prompt_override）。
      只用 gpu33:0 / gpu33:3 / gpu36:0 / gpu36:1（绝不用 gpu33:1）。出完把各镜“当前版本”恢复成原来的，不定稿。
  .venv/Scripts/python.exe tools/ab_voice_fix.py analyze
      每版：抽音轨（wav + mp3 试听短片）、SenseVoice 回听 vs 剧本台词（CER）、男声测量（基频中位 / 起伏 / 语速）、
      运动量（take.qc.motion，QCV 的 motion_qc），写 data/ab/voice_fix/table.md。

不改剧本 / 提示词 / 角色表，不做内容检测；台词只用于字符比对。
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/post", "services/render_router", "packages/schema"):
    sys.path.insert(0, str(ROOT / p))

from ns_post.tts import SenseVoiceAsr, asr_limit, char_error_rate, load_voice_config, normalize  # noqa: E402

API = "http://127.0.0.1:8800"
OUT = ROOT / "data" / "ab" / "voice_fix"
STATE = OUT / "jobs.json"
TIMELINE = ROOT / "data" / "episodes" / "ep02.timeline.json"
LANES = [0, 3, "gpu36:0", "gpu36:1", 1]     # gpu36:2 只给 >260 帧；gpu33:1 在 fredw-0b 训练结束、去锁后才加入（fredw-92 12:40 通知）
LANE_IDS = {0: "gpu33:0", 1: "gpu33:1", 3: "gpu33:3", "gpu36:0": "gpu36:0", "gpu36:1": "gpu36:1"}
S6_MAX = 4
S6_WANT = "您"


# ---------------- 通用 ----------------

def http(method: str, path: str, body: dict | None = None, timeout: float = 60) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"jobs": [], "orig_active": {}}


def save_state(st: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def speech_lines() -> dict[int, dict]:
    """ep02 时间线 speech 里的对白（kind=dialogue）：镜号 → {speaker, text}"""
    tl = json.loads(TIMELINE.read_text(encoding="utf-8"))
    return {s["shot"]: s for s in tl["speech"] if s["kind"] == "dialogue"}


def takes_of(shot: int) -> dict:
    from ns_render import pipeline as P
    return P.load_takes(f"ep02-S{shot}")


# ---------------- ASR / 声音测量 ----------------

_ASR = None


def asr_detail(wav16: Path) -> dict:
    global _ASR
    if _ASR is None:
        _ASR = SenseVoiceAsr(load_voice_config(), num_threads=4)
    return _ASR.transcribe_detail([wav16])[0]


def extract_audio(video: Path, stem: str) -> tuple[Path, Path, Path]:
    """→ (16 kHz 单声道 ASR 用, 48 kHz 试听 wav, 试听 mp3)"""
    clips = OUT / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    w16 = OUT / "asr" / f"{stem}.16k.wav"
    w16.parent.mkdir(parents=True, exist_ok=True)
    wav, mp3 = clips / f"{stem}.wav", clips / f"{stem}.mp3"
    ffmpeg("-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(w16))
    ffmpeg("-i", str(video), "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(wav))
    ffmpeg("-i", str(video), "-vn", "-c:a", "libmp3lame", "-b:a", "160k", str(mp3))
    return w16, wav, mp3


def read_wav(p: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(p), "rb") as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    return (x.reshape(-1, ch).mean(axis=1) if ch > 1 else x), sr


def f0_track(x: np.ndarray, sr: int, fmin: float = 60.0, fmax: float = 320.0) -> np.ndarray:
    """简单归一化自相关基频（40 ms 窗 / 10 ms 步）；清音 / 静音帧记 NaN"""
    win, hop = int(0.04 * sr), int(0.01 * sr)
    lo, hi = int(sr / fmax), int(sr / fmin)
    rms_all = np.sqrt(np.mean(x ** 2)) + 1e-9
    out = []
    for i in range(0, max(0, len(x) - win), hop):
        f = x[i:i + win] * np.hanning(win)
        if np.sqrt(np.mean(f ** 2)) < 0.3 * rms_all:
            out.append(np.nan)
            continue
        ac = np.correlate(f, f, mode="full")[win - 1:]
        ac = ac / (ac[0] + 1e-9)
        k = lo + int(np.argmax(ac[lo:hi]))
        out.append(sr / k if ac[k] > 0.45 else np.nan)
    return np.array(out)


def voice_metrics(w16: Path, t0: float | None, t1: float | None, n_chars: int) -> dict:
    """台词时间段内：基频中位（Hz）、起伏（半音标准差，越小越平）、语速（字/秒）"""
    x, sr = read_wav(w16)
    if t0 is not None and t1 is not None and t1 > t0:
        x = x[int(max(0, t0 - 0.05) * sr): int((t1 + 0.1) * sr)]
    f0 = f0_track(x, sr)
    v = f0[~np.isnan(f0)]
    if len(v) < 5:
        return {"f0_med": None, "f0_st": None, "rate": None, "voiced_s": round(len(v) * 0.01, 2)}
    med = float(np.median(v))
    st = 12 * np.log2(v / med)
    st = st[np.abs(st) < 12]          # 去掉倍频 / 半频误判
    dur = (t1 - t0) if (t0 is not None and t1 is not None and t1 > t0) else None
    return {"f0_med": round(med, 1), "f0_st": round(float(np.std(st)), 2),
            "rate": round(n_chars / dur, 2) if dur else None, "voiced_s": round(len(v) * 0.01, 2)}


def listen(video: Path, stem: str, line: dict) -> dict:
    from ns_post.h3_dialogue import split_lines
    w16, wav, mp3 = extract_audio(video, stem)
    d = asr_detail(w16)
    rows = split_lines(d, [line["text"]])
    r = rows[0]
    heard = str(d.get("text") or "")
    cer = round(char_error_rate(line["text"], heard), 3)
    res = {"heard": heard, "cer": cer, "limit": asr_limit(line["text"]), "t0": r["t0"], "t1": r["t1"],
           "event": d.get("event"), "wav": rel(wav), "mp3": rel(mp3)}
    res["voice"] = voice_metrics(w16, r["t0"], r["t1"], len(normalize(line["text"])))
    return res


def rel(p: Path) -> str:
    return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")


def s6_ok(heard: str) -> bool:
    return S6_WANT in heard and char_error_rate("那我…明天还您。", heard) <= asr_limit("那我…明天还您。")


# ---------------- 出片 ----------------

def lane_load() -> dict:
    info = http("GET", "/api/render/lanes")["lanes"]
    return {ln["id"]: (ln.get("comfy_running", 0) or 0) + (ln.get("comfy_pending", 0) or 0) + (ln.get("queued", 0) or 0)
            for ln in info if ln.get("ok")}


def pick_lane(busy_mine: set) -> object | None:
    load = lane_load()
    locked = {ln["id"] for ln in http("GET", "/api/render/lanes")["lanes"] if ln.get("train_locked")}
    cands = [g for g in LANES if LANE_IDS[g] in load and LANE_IDS[g] not in busy_mine and LANE_IDS[g] not in locked]
    if not cands:
        return None
    return min(cands, key=lambda g: (load[LANE_IDS[g]], LANES.index(g)))


def submit(shot: int, seed: int, lane, mode: str) -> dict:
    body = {"seed": seed, "gpu": lane}
    if mode != "use":
        body["last_frame_mode"] = mode
    r = http("POST", f"/api/shots/ep02-S{shot}/video-jobs", body)
    return {"shot": shot, "seed": seed, "lane": LANE_IDS[lane], "job_id": r.get("job_id") or r.get("id"),
            "mode": mode, "state": "queued", "warnings": r.get("warnings"), "submitted": time.strftime("%H:%M:%S")}


def render(per_shot: int, max_inflight: int, mode: str) -> None:
    st = load_state()
    lines = speech_lines()
    male = [s for s, ln in sorted(lines.items()) if ln["speaker"] == "gu_chen"]
    print("顾沉有台词的镜：", male, flush=True)
    for s in male + [6]:
        st["orig_active"].setdefault(str(s), takes_of(s).get("active", {}).get("video"))
    rng = random.Random()
    todo = [(s, None) for s in male for _ in range(per_shot - sum(j["shot"] == s for j in st["jobs"]))]
    save_state(st)
    while True:
        live = [j for j in st["jobs"] if j["state"] in ("queued", "running")]
        for j in live:
            try:
                g = http("GET", f"/api/jobs/{j['job_id']}")
            except Exception as e:  # noqa: BLE001
                print("poll fail", j["job_id"], e, flush=True)
                continue
            j["state"] = g.get("state")
            if j["state"] == "done":
                j["take"] = g.get("take")
                j["file"] = (g.get("take_params") or {}).get("file") or None
                print("done", j, flush=True)
                if j["shot"] == 6:
                    tk = next(t for t in takes_of(6)["takes"] if t["stage"] == "video" and t["n"] == j["take"])
                    res = listen(ROOT / "data" / tk["file"], f"S6_seed{j['seed']}", lines[6])
                    j["heard"], j["cer"] = res["heard"], res["cer"]
                    print("S6 听到：", res["heard"], flush=True)
            elif j["state"] in ("error", "failed", "cancelled"):
                j["error"] = g.get("error")
                print("FAILED", j, flush=True)
        s6 = [j for j in st["jobs"] if j["shot"] == 6]
        s6_won = any(s6_ok(j.get("heard") or "") for j in s6)
        s6_live = any(j["state"] in ("queued", "running") for j in s6)
        want = list(todo)
        if not s6_won and not s6_live and len(s6) < S6_MAX:
            want.insert(0, (6, None))
        live = [j for j in st["jobs"] if j["state"] in ("queued", "running")]
        if want and len(live) < max_inflight:
            lane = pick_lane({j["lane"] for j in live})
            if lane is not None:
                shot = want[0][0]
                seed = rng.randrange(10 ** 13, 3 * 10 ** 14)
                j = submit(shot, seed, lane, mode)
                st["jobs"].append(j)
                if (shot, None) in todo:
                    todo.remove((shot, None))
                print("submitted", j, flush=True)
        save_state(st)
        live = [j for j in st["jobs"] if j["state"] in ("queued", "running")]
        s6_more = not s6_won and len(s6) < S6_MAX
        if not live and not todo and not s6_more:
            break
        time.sleep(30)
    restore_active(st)
    print("全部完成", flush=True)


def restore_active(st: dict) -> None:
    for s, n in st["orig_active"].items():
        cur = takes_of(int(s)).get("active", {}).get("video")
        if n is not None and cur != n:
            http("POST", f"/api/shots/ep02-S{s}/takes/video/{n}/activate", {})
            print(f"S{s} 当前版本恢复为 {n}（新出的 {cur} 留在版本链里）", flush=True)


# ---------------- 试听表 ----------------

def analyze() -> None:
    st = load_state()
    lines = speech_lines()
    rows = []
    shots = sorted({j["shot"] for j in st["jobs"]})
    for s in shots:
        tk = takes_of(s)
        base_n = st["orig_active"].get(str(s))
        items = [("原版", base_n)] + [(f"新·seed {j['seed']}", j.get("take")) for j in st["jobs"]
                                       if j["shot"] == s and j["state"] == "done"]
        for label, n in items:
            t = next((x for x in tk["takes"] if x["stage"] == "video" and x["n"] == n), None)
            if t is None:
                continue
            seed = t["params"].get("seed")
            res = listen(ROOT / "data" / t["file"], f"S{s}_take{n}_seed{seed}", lines[s])
            mo = (t.get("qc") or {}).get("motion") or {}
            if not mo:
                from ns_render import motion_qc as MQ
                mo = MQ.video_motion(ROOT / "data" / t["file"])
            rows.append({"shot": s, "label": label, "take": n, "seed": seed, "file": "data/" + t["file"],
                         "lane": t["params"].get("gpu"), "mode": t["params"].get("last_frame_mode") or "use",
                         "line": lines[s]["text"], "speaker": lines[s]["speaker_name"], **res,
                         "motion": {"verdict": mo.get("verdict"), "labels": mo.get("labels"),
                                    **{k: (mo.get("metrics") or {}).get(k) for k in
                                       ("mean_diff", "still_frac", "frozen_tail_s")}}})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    (OUT / "table.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    write_table(rows, st)


def fmt(v, nd=2):
    return "—" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def write_table(rows: list[dict], st: dict) -> None:
    modes = sorted({j["mode"] for j in st["jobs"]})
    L = ["# 顾沉声音 / S6“您” 换种子试听表（VOX，2026-10-31）", "",
         "项目方原话：“男生的声音有点生硬”；“不接受 S6 念成了“明天还你””。",
         "",
         "- 每镜第一行“原版”= 现在 ep02 H3 原声版用的那一版；其余是同一定稿首尾帧、剧本提示词原样、只换种子的新版本"
         f"（经 POST video-jobs，last_frame_mode = {', '.join(modes)}）。没有定稿、没有改“当前版本”。",
         "- **已叫停**：fredw-92 12:55 通知项目方判定现有视频都不能用、视频配方由 MOT 替换 → 不再提交新种子，排队中的已取消；"
         "下表只有叫停前已出完的版本（旧配方，仅供听声音参考）。QCV 当时没有推荐变体，用的是标准做法（首尾帧都给）。",
         "- 试听：`clips/` 下每版一个 .mp3（整条 H3 原声，含配乐），A/B 时直接点开。",
         "- 回听 = SenseVoice（和合成器同一个模型）；CER 是对剧本台词的字符差。",
         "- 男声测量（只在台词时间段内）：基频中位 Hz；起伏 = 基频的半音标准差（数值越小音调越平）；"
         "语速 = 剧本字数 / 台词时长。只是测量，选哪版由项目方听了定。",
         "- 运动量 = QCV 的 motion_qc（平均帧差 >1 算有动作；静止帧占比；结尾定住秒数）。",
         "",
         "| 镜 | 说话人 | 版本 | take | 试听 | 视频 | 听到的 | CER | 开口 s | 基频 Hz | 起伏 半音 | 语速 字/s | 运动 | 平均帧差 | 静止帧 | 结尾定住 s |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        v, m = r["voice"], r["motion"]
        ok = "" if r["cer"] <= r["limit"] else " ✗"
        L.append(f"| S{r['shot']} | {r['speaker']} | {r['label']} | {r['take']} | [{Path(r['mp3']).name}]({Path(r['mp3']).relative_to('data/ab/voice_fix').as_posix()}) "
                 f"| `{r['file']}` | {r['heard']} | {r['cer']:.2f}{ok} | {fmt(r['t0'])} | {fmt(v['f0_med'], 0)} "
                 f"| {fmt(v['f0_st'])} | {fmt(v['rate'])} | {m.get('verdict') or '—'} | {fmt(m.get('mean_diff'))} "
                 f"| {fmt(m.get('still_frac'))} | {fmt(m.get('frozen_tail_s'))} |")
    s6 = [r for r in rows if r["shot"] == 6 and r["label"] != "原版"]
    L += ["", "## S6（目标：SenseVoice 听到“您”）", ""]
    won = [r for r in s6 if s6_ok(r["heard"])]
    L.append(f"新出 {len(s6)} 版（上限 {S6_MAX}）：" + ("；".join(f"seed {r['seed']} 听到“{r['heard']}”" for r in s6) or "无"))
    L.append("")
    L.append(("**有听到“您”的版本**：" + "、".join(f"take {r['take']}（seed {r['seed']}）" for r in won))
             if won else (f"**新出的 {len(s6)} 版都没有听到“您”**。" + (
                 "4 版上限已用完，换种子解决不了；可选：变声 / 剧本方改字 / 人工配音，由项目方定。" if len(s6) >= S6_MAX else
                 "fredw-92 12:55 通知旧视频配方作废（MOT 换配方），重出已叫停，没出满 4 版；新配方出片后再按同法回听。")))
    (OUT / "table.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("写好", OUT / "table.md")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--per-shot", type=int, default=2)
    r.add_argument("--max-inflight", type=int, default=3)
    r.add_argument("--mode", default="use", choices=["use", "none", "auto"])
    sub.add_parser("analyze")
    sub.add_parser("restore")
    sub.add_parser("finish")   # 不再提交：等已在跑的收尾 → 恢复当前版本 → 出试听表（fredw-92 12:55 叫停重出）
    a = ap.parse_args()
    if a.cmd == "render":
        render(a.per_shot, a.max_inflight, a.mode)
    elif a.cmd == "finish":
        st = load_state()
        while True:
            for j in st["jobs"]:
                if j["state"] in ("queued", "running"):
                    g = http("GET", f"/api/jobs/{j['job_id']}")
                    j["state"], j["take"] = g.get("state"), g.get("take")
            save_state(st)
            if not any(j["state"] in ("queued", "running") for j in st["jobs"]):
                break
            time.sleep(60)
        restore_active(st)
        analyze()
    elif a.cmd == "analyze":
        analyze()
    else:
        restore_active(load_state())
