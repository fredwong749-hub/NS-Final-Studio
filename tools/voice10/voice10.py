"""VOICE10：series10 角色音色候选（项目方 2026-11-01 一键答复“重做候选我来挑”）。

方法与旁白 QAg 相同：Qwen3-TTS 1.7B VoiceDesign 按文字描述设计 → ref.wav；Fun-CosyVoice3 0.5B zero-shot 以 ref.wav 复刻
念这个人物自己的两句台词 → sample.wav。文字设计的合成声，不克隆任何真人。

描述只用写作模型 P1 的字段原样拼接（不改写、不评价）：
    instruct = "<gender_en>, <age> years old, <voice_phrase>"   ← P1_storyline.json characters[].gender / age / voice_phrase
两句试听台词 = 这个人物在 series10_v1 P3 里最长的两句 dialogue（按可读字数，等长取靠前的；机械规则）。
ref 文本 = 这个人物全部 dialogue 按剧本顺序拼接（ns_post.speakers.tts_text 清洗），够 ~60 字就停。

    python tools/voice10/voice10.py plan  [--extra cid:N ...]   写 data/assets/voices/<cid>_cand/<cN>/meta.json（待生成）
    python tools/voice10/voice10.py run                         上传 → gpu36 CPU/GPU 生成 → 拉回 ref.wav / sample.wav
    python tools/voice10/voice10.py check                       自动检查（SenseVoice CER、f0、HNR、时长、削波）写回 meta.json
    python tools/voice10/voice10.py autopick [--dry]               按检查每人自动选一个写 voices.json（项目方 2026-11-01 原话授权）
    python tools/voice10/voice10.py drop                        检查没过的挪进 <cid>_cand/_failed/（不进候选列表）

候选目录：data/assets/voices/<cid>_cand/<cN>/{ref.wav, sample.wav, meta.json}；后端 /api/voices/s10 只列 checks.pass=true 的。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "data" / "pipeline" / "runs" / "series10_v1"
VOICES = ROOT / "data" / "assets" / "voices"
sys.path.insert(0, str(ROOT / "services" / "post"))
from ns_post.speakers import tts_text  # noqa: E402
from ns_post.tts import char_error_rate  # noqa: E402

REMOTE = "/root/work/fredw/voice10"
VENV = "/root/work/fredw/venv_tts"
VD_MODEL = ("/root/work/fredw/hf/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign/snapshots/"
            "5ecdb67327fd37bb2e042aab12ff7391903235d3")
COSY_MODEL = ("/root/work/fredw/hf/hub/models--FunAudioLLM--Fun-CosyVoice3-0.5B-2512/snapshots/"
              "29e01c4e8d000f4bcd70751be16fa94bf3d85a18")
BASE_SEED = 20261101
N_CAND = 4
REF_CHARS = 60
GENDER_EN = {"女": "female", "男": "male", "female": "female", "male": "male"}

# 自动检查门槛（机械，不评价音色好坏；f0 范围只防“性别/年龄完全跑偏”和测不出音高的坏样本）
LIMITS = {
    "cer_max": 0.2,                      # SenseVoice 回听两句合起来的字错率
    "f0": {"female": (150, 400), "male": (70, 190)},
    "hnr_min": 3.0,                      # dB；低于此多为噪声 / 破音
    "dur_min": 1.5,                      # 秒（旧 A 轨 0:01 那种坏片）
    "ref_dur": (2.5, 30.0),              # ref.wav 合理长度
    "clip_peak": 0.999,                  # |x| ≥ 此值算削波样点
    "clip_frac_max": 0.0005,
}


def _j(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def cast() -> list[dict]:
    """P1 角色表 ∩ P3 有 dialogue 的人（旁白不在内，旁白仍是 QAg）"""
    chars = _j(RUN / "P1_storyline.json")["characters"]
    lines: dict[str, list[tuple[str, str]]] = {}
    for ep in sorted(RUN.glob("ep[0-9][0-9]/P3_ep*_screenplay.json")):
        d = _j(ep)
        for sc in d["scenes"]:
            for i, ln in enumerate(sc["lines"]):
                if ln.get("kind") == "dialogue" and ln.get("speaker"):
                    t = tts_text(ln["text"])
                    if t:
                        lines.setdefault(ln["speaker"], []).append((f"ep{d['episode']:02d}-S{sc['no']}#{i}", t))
    out = []
    for c in chars:
        own = lines.get(c["name"])
        if not own:
            continue
        n = lambda t: sum(ch.isalnum() for ch in t)  # noqa: E731
        two = sorted(sorted(range(len(own)), key=lambda k: (-n(own[k][1]), k))[:2])
        ref, refs = "", []
        for k, t in own:
            if len(ref) >= REF_CHARS:
                break
            ref += t
            refs.append(k)
        g = GENDER_EN.get(str(c.get("gender")), str(c.get("gender")))
        vp = c.get("voice_phrase")
        out.append({
            "cid": c["char_id"], "name": c["name"], "gender": g, "age": c.get("age"),
            "voice_phrase": vp,
            "instruct": f"{g}, {c.get('age')} years old, {vp}" if vp else f"{g}, {c.get('age')} years old",
            "instruct_source": ("P1_storyline.json characters[].gender/age/voice_phrase 原样拼接" if vp
                                else "P1 没有 voice_phrase：只用 gender/age"),
            "lines": [own[k][1] for k in two], "line_ids": [own[k][0] for k in two],
            "ref_text": ref, "ref_line_ids": refs,
        })
    return out


def cand_dirs(cid: str) -> list[Path]:
    d = VOICES / f"{cid}_cand"
    return sorted((p for p in d.glob("c*") if p.is_dir() and (p / "meta.json").exists()),
                  key=lambda p: int(p.name[1:]))


def plan(extra: dict[str, int]) -> None:
    for c in cast():
        d = VOICES / f"{c['cid']}_cand"
        d.mkdir(parents=True, exist_ok=True)
        have = cand_dirs(c["cid"])
        used = {int(p.name[1:]) for p in have} | {int(p.name[1:]) for p in (d / "_failed").glob("c*")}
        want = N_CAND - len(have) if not have else extra.get(c["cid"], 0)
        k = max(used, default=0)
        for _ in range(want):
            k += 1
            cd = d / f"c{k}"
            cd.mkdir()
            meta = {
                "schema": "nsfs.voice_candidate/1", "cid": c["cid"], "name": c["name"], "cand": f"c{k}",
                "status": "planned", "made_by": "VOICE10 2026-11-01（tools/voice10/voice10.py）",
                "owner_decision_ref": "项目方 2026-11-01 一键答复：重做候选我来挑",
                "design": {"engine": "Qwen3-TTS 1.7B VoiceDesign（Apache-2.0）",
                           "weights": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign@5ecdb67327fd37bb2e042aab12ff7391903235d3",
                           "instruct": c["instruct"], "instruct_source": c["instruct_source"],
                           "language": "Chinese", "seed": BASE_SEED + 100 * k + len(c["cid"]),
                           "note": "文字描述设计的合成声，不克隆任何真人"},
                "ref_wav": "ref.wav", "ref_text": c["ref_text"],
                "ref_text_source": "series10_v1 P3 该人物 dialogue（tts_text 清洗，逐字）：" + "、".join(c["ref_line_ids"]),
                "clone": {"engine": "cosyvoice3_zs",
                          "model": "Fun-CosyVoice3-0.5B-2512（Apache-2.0）zero-shot，prompt = 本 ref.wav + ref_text",
                          "weights": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512@29e01c4e8d000f4bcd70751be16fa94bf3d85a18",
                          "seed": BASE_SEED},
                "sample_wav": "sample.wav", "sample_lines": c["lines"], "sample_line_ids": c["line_ids"],
                "sample_text": "".join(c["lines"]),
            }
            (cd / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            print("planned", cd.relative_to(ROOT))


def ssh(cmd: str, timeout=7200) -> str:
    p = _rssh().run_retry("gpu36", cmd, timeout=timeout, tries=1, text=True)   # 原来不重试：tries=1 保持一致
    if p.returncode:
        raise RuntimeError(f"ssh {cmd[:80]}… rc={p.returncode}\n{p.stderr[-1500:]}")
    return p.stdout


def _rssh():
    """K-OPS-N07 / SYSARCH 4-1：远程命令统一走 tools/netfix/rssh.run_retry（常驻主连接；服务器上 OFFLINE_SELF 调本机 = 本机执行）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_rssh_41", Path(__file__).resolve().parents[2] / "tools/netfix/rssh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def scp(src: str, dst: str) -> None:
    subprocess.run(["scp", "-q", "-o", "BatchMode=yes", src, dst], check=True, timeout=600)


def pending() -> list[tuple[Path, dict]]:
    out = []
    for d in sorted(VOICES.glob("*_cand")):
        for cd in cand_dirs(d.name[:-5]):
            m = _j(cd / "meta.json")
            if not ((cd / "ref.wav").exists() and (cd / "sample.wav").exists()):
                out.append((cd, m))
    return out


def _hb(device: str, label: str | None, step: int | None) -> None:
    """GPU 面板心跳（K-OPS-G01，data/gpu_heartbeats/）：只在 gpu36 的卡上跑时写（device=cpu 不占卡不写）；
    label=None → 结束删心跳。出错不影响生成"""
    try:
        if not str(device).startswith("cuda"):
            return
        sp = str(ROOT / "services" / "agent")
        if sp not in sys.path:
            sys.path.append(sp)
        from ns_agent import comfy_tag as CT
        if label is None:
            CT.heartbeat_done("VOICE10", hb_id="VOICE10-run")
            return
        gpu = int(device.split(":", 1)[1]) if ":" in device else 0
        CT.heartbeat("VOICE10", label, kind="voice", server="gpu36", gpu=gpu, step=step, steps=2,
                     hb_id="VOICE10-run", ttl=7200)        # 每步是一次长 ssh（≤ 2 h），中间不更新
    except Exception:  # noqa: BLE001
        pass


def run(device: str) -> None:
    todo = pending()
    if not todo:
        print("nothing to run")
        return
    rp = lambda cd, f: f"{REMOTE}/out/{cd.parent.name}/{cd.name}/{f}"  # noqa: E731
    design = {"model_dir": VD_MODEL, "device": device,
              "items": [{"instruct": m["design"]["instruct"], "text": m["ref_text"], "seed": m["design"]["seed"],
                         "out": rp(cd, "ref.wav")} for cd, m in todo]}
    clone = {"model_dir": COSY_MODEL, "seed": BASE_SEED,
             "items": [{"ref_wav": rp(cd, "ref.wav"), "ref_text": m["ref_text"], "lines": m["sample_lines"],
                        "out": rp(cd, "sample.wav")} for cd, m in todo]}
    tmp = ROOT / "data" / "assets" / "voices" / "_voice10_tmp"
    tmp.mkdir(exist_ok=True)
    (tmp / "design.json").write_text(json.dumps(design, ensure_ascii=False), encoding="utf-8")
    (tmp / "clone.json").write_text(json.dumps(clone, ensure_ascii=False), encoding="utf-8")
    ssh(f"mkdir -p {REMOTE}/out && " + " && ".join(f"mkdir -p {REMOTE}/out/{cd.parent.name}/{cd.name}" for cd, _ in todo))
    here = Path(__file__).parent
    for f in ("remote_design.py", "remote_clone.py"):
        scp(str(here / f), f"gpu36:{REMOTE}/{f}")
    for f in ("design.json", "clone.json"):
        scp(str(tmp / f), f"gpu36:{REMOTE}/{f}")
    env = f"export HF_HOME=/root/work/fredw/hf HF_HUB_OFFLINE=1 OMP_NUM_THREADS=16 CUDA_VISIBLE_DEVICES=''"
    chars = "、".join(dict.fromkeys(cd.parent.name[:-5] for cd, _ in todo))
    _hb(device, f"试听音色 · {chars} 设计音色（{len(todo)} 个候选）", 1)
    try:
        t0 = time.time()
        print(ssh(f"{env}; cd {REMOTE} || exit 1; {VENV}/bin/python remote_design.py design.json 2>>design.err")[-3000:])
        print("design", round(time.time() - t0), "s", flush=True)
        _hb(device, f"试听音色 · {chars} 克隆试听句（{len(todo)} 个候选）", 2)
        t0 = time.time()
        print(ssh(f"{env} PYTHONPATH={VENV}/cosy_overlay; cd {REMOTE} || exit 1; "
                  f"{VENV}/bin/python remote_clone.py clone.json 2>>clone.err")[-3000:])
        print("clone", round(time.time() - t0), "s", flush=True)
    finally:
        _hb(device, None, None)
    for cd, m in todo:
        for f in ("ref.wav", "sample.wav"):
            scp(f"gpu36:{rp(cd, f)}", str(cd / f))
        m["status"] = "generated"
        m["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        m["runtime"] = f"gpu36 {VENV}（{device}；三张卡都在出图/出片，按 run_narrator.sh 规则无空闲卡走 CPU）" \
            if device == "cpu" else f"gpu36 {VENV}（{device}）"
        (cd / "meta.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)


def clip_stats(p: Path) -> tuple[float, float]:
    import numpy as np
    sys.path.insert(0, str(ROOT / "data" / "review_pages" / "narrator_pick" / "_tools"))
    from common import read_wav
    x, _ = read_wav(p)
    a = np.abs(x)
    return float(a.max()), float((a >= LIMITS["clip_peak"]).mean())


def hnr_corrected(p: Path, fmin: float = 60.0, fmax: float = 400.0, win_s: float = 0.06) -> float:
    """HNR（dB）：Hann 窗自相关再除以窗自身的自相关（Boersma 1993），窗长 60 ms ≥ 3.6 个 60 Hz 周期。
    旁白挑选用的 common.metrics 版本没做窗校正、音高下限 90 Hz、窗 40 ms：滞后越长（音高越低）读数越被压低——
    实测旧 Kokoro zm_029（干净合成男声，f0 110）只读到 2.4 dB，顾沉候选 0.7–2.4 dB；校正后 3.1–7.2 dB。所以低音男声改用本函数。"""
    import numpy as np
    from common import read_wav
    x, sr = read_wav(p)
    win, hop = int(win_s * sr), int(0.01 * sr)
    lo, hi = int(sr / fmax), int(sr / fmin)
    rms = np.sqrt(np.mean(x ** 2)) + 1e-9
    w = np.hanning(win)
    aw = np.correlate(w, w, mode="full")[win - 1:]
    aw = aw / aw[0]
    out = []
    for i in range(0, max(0, len(x) - win), hop):
        f = x[i:i + win] * w
        if np.sqrt(np.mean(f ** 2)) < 0.3 * rms:
            continue
        ac = np.correlate(f, f, mode="full")[win - 1:]
        ac = ac / (ac[0] + 1e-9)
        r = ac[lo:hi] / np.maximum(aw[lo:hi], 1e-3)
        v = float(min(r[int(np.argmax(r))], 0.999))
        if v > 0.45:
            out.append(10 * np.log10(v / (1 - v)))
    return round(float(np.median(out)), 1) if out else 0.0


def check() -> None:
    sys.path.insert(0, str(ROOT / "data" / "review_pages" / "narrator_pick" / "_tools"))
    from common import asr, metrics  # 旁白挑选时同一套：SenseVoice（sherpa-onnx）回听 + 自相关 f0/HNR
    todo = [(cd, _j(cd / "meta.json")) for d in sorted(VOICES.glob("*_cand")) for cd in cand_dirs(d.name[:-5])
            if (cd / "sample.wav").exists()]
    heard = asr([cd / "sample.wav" for cd, _ in todo])
    for (cd, m), h in zip(todo, heard):
        g = "female" if m["design"]["instruct"].startswith("female") else "male"
        s, r = metrics(cd / "sample.wav"), metrics(cd / "ref.wav")
        hn = hnr_corrected(cd / "sample.wav")
        peak, frac = clip_stats(cd / "sample.wav")
        rpeak, rfrac = clip_stats(cd / "ref.wav")
        cer = round(char_error_rate(m["sample_text"], h), 3)
        lo, hi = LIMITS["f0"][g]
        items = {
            "cer": {"value": cer, "asr": h, "limit": f"≤ {LIMITS['cer_max']}", "pass": cer <= LIMITS["cer_max"]},
            "f0_hz": {"value": s["f0"], "limit": f"{lo}–{hi}（{g}）", "pass": lo <= s["f0"] <= hi},
            "hnr_db": {"value": hn, "raw_uncorrected": s["hnr"], "method": "hnr_corrected（Boersma 窗校正，60 ms / 60 Hz）",
                       "limit": f"≥ {LIMITS['hnr_min']}", "pass": hn >= LIMITS["hnr_min"]},
            "duration_s": {"value": s["dur"], "limit": f"> {LIMITS['dur_min']}", "pass": s["dur"] > LIMITS["dur_min"]},
            "clipping": {"value": {"peak": round(peak, 4), "frac": round(frac, 6)},
                         "limit": f"削波样点占比 ≤ {LIMITS['clip_frac_max']}", "pass": frac <= LIMITS["clip_frac_max"]},
            "ref_ok": {"value": {"dur": r["dur"], "f0": r["f0"], "peak": round(rpeak, 4), "clip_frac": round(rfrac, 6)},
                       "limit": f"ref 时长 {LIMITS['ref_dur'][0]}–{LIMITS['ref_dur'][1]} s 且不削波",
                       "pass": LIMITS["ref_dur"][0] <= r["dur"] <= LIMITS["ref_dur"][1] and rfrac <= LIMITS["clip_frac_max"]},
        }
        m["checks"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": "tools/voice10/voice10.py check",
                       "items": items, "pass": all(v["pass"] for v in items.values()),
                       "f0_sd_st": s["f0_sd"], "ref_f0_hz": r["f0"]}
        m["status"] = "passed" if m["checks"]["pass"] else "failed"
        m["ref_sha256"] = hashlib.sha256((cd / "ref.wav").read_bytes()).hexdigest()
        (cd / "meta.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        bad = [k for k, v in items.items() if not v["pass"]]
        print(cd.relative_to(VOICES), "PASS" if not bad else f"FAIL {bad}", f"cer={cer} f0={s['f0']} hnr={hn} (raw {s['hnr']}) "
              f"dur={s['dur']} peak={peak:.3f} ref={r['dur']}s asr={h}")


OWNER_QUOTE = "音色问题,采取qad类似模型给林晚,和其他男人的,我来不及筛选"


def rank_key(m: dict):
    """自动选的排序（机械）：①回听字错率最低 ②削波样点最少 ③复刻出的 sample 音高最贴近设计出的 ref 音高（复刻忠实）④编号小"""
    it = m["checks"]["items"]
    return (it["cer"]["value"], it["clipping"]["value"]["frac"],
            abs(it["f0_hz"]["value"] - (m["checks"].get("ref_f0_hz") or it["f0_hz"]["value"])), int(m["cand"][1:]))


def autopick(dry: bool) -> None:
    """项目方 2026-11-01 原话授权按检查自动选：每个人物在过检候选里按 rank_key 取第一，经 ns_api.voice_preview.apply_pick
    （与界面“用 B”同一写入路径：改前重读、整份备份、撤销记录）写 config/voices.json；记审计 + owner_decisions。"""
    sys.path.insert(0, str(ROOT / "services" / "api"))
    from ns_api import voice_preview as V
    from ns_api.auth import audit_line
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    picks = []
    for c in cast():
        ms = [_j(cd / "meta.json") for cd in cand_dirs(c["cid"])]
        ok = sorted((m for m in ms if (m.get("checks") or {}).get("pass")), key=rank_key)
        if not ok:
            print(c["cid"], "没有过检候选，不选")
            continue
        best = ok[0]
        it = best["checks"]["items"]
        reason = (f"{len(ok)} 个过检候选里按 回听字错率最低 → 削波最少 → 复刻音高最贴近设计 ref 选 {best['cand']}："
                  f"CER {it['cer']['value']}、时长 {it['duration_s']['value']} s、f0 {it['f0_hz']['value']} Hz（{it['f0_hz']['limit']}）、"
                  f"HNR {it['hnr_db']['value']} dB、峰值 {it['clipping']['value']['peak']}；其余："
                  + "；".join(f"{m['cand']} CER {m['checks']['items']['cer']['value']} f0 {m['checks']['items']['f0_hz']['value']}"
                             for m in ok[1:]))
        print(c["cid"], "->", best["cand"], reason)
        picks.append((c, best, reason))
        if dry:
            continue
        r = V.apply_pick(c["cid"], best["cand"], note="按自动检查自动选", decision={
            "by": "owner", "auto": True, "quote": OWNER_QUOTE, "quote_date": "2026-11-01",
            "how": "tools/voice10/voice10.py autopick（项目方原话授权按检查自动选；声音页可一键换成其他候选）",
            "reason": reason})
        audit_line({"user": "VOICE10（项目方原话授权）", "role": "agent", "method": "POST",
                    "path": f"/api/voices/{c['cid']}/pick", "object": {"cand": best["cand"], "undo_id": r["undo_id"]},
                    "status": 200, "note": "autopick"})
    if dry or not picks:
        return
    od = RUN / "owner_decisions.json"
    lst = _j(od)
    lst.append({"date": "2026-11-01", "topic": "series10 角色音色（自动选）", "quote": OWNER_QUOTE,
                "replaces": "2026-11-01 一键答复“重做候选我来挑”（待你挑）",
                "done": "QAg 同法（Qwen3-TTS VoiceDesign + Fun-CosyVoice3）每人 4 个候选，按自动检查选定并写 config/voices.json"
                        "（series=series10_v1；旁白仍 QAg）：" + "；".join(f"{c['name']}={b['cand']}" for c, b, _ in picks)
                        + "；其余候选留在声音页可一键换",
                "at": now, "by": "VOICE10"})
    nl = "\n"
    od.write_text("[" + nl + ("," + nl).join(" " + json.dumps(x, ensure_ascii=False) for x in lst) + nl + "]" + nl,
                  encoding="utf-8")  # 原样式：一条一行


def drop() -> None:
    for d in sorted(VOICES.glob("*_cand")):
        for cd in cand_dirs(d.name[:-5]):
            if _j(cd / "meta.json").get("status") == "failed":
                (d / "_failed").mkdir(exist_ok=True)
                shutil.move(str(cd), str(d / "_failed" / cd.name))
                print("dropped", cd.relative_to(VOICES))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "run", "check", "drop", "cast", "autopick"])
    ap.add_argument("--extra", nargs="*", default=[], help="cid:N 再补 N 个候选")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.cmd == "cast":
        print(json.dumps(cast(), ensure_ascii=False, indent=1))
    elif a.cmd == "plan":
        plan({k: int(v) for k, v in (x.split(":") for x in a.extra)})
    elif a.cmd == "run":
        run(a.device)
    elif a.cmd == "check":
        check()
    elif a.cmd == "autopick":
        autopick(a.dry)
    else:
        drop()
