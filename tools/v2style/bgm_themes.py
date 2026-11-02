"""STYLE-V2 整季主题配乐候选（3 主题 × 幻想 / 现实两种编配）。

    .venv/Scripts/python.exe tools/v2style/bgm_themes.py run        生成（gpu33:3）→ 打分（gpu36 CPU）→ 交付响度 → 闸门 → 试听页
    .venv/Scripts/python.exe tools/v2style/bgm_themes.py page       只重写试听页（读 data/music/v2_style/themes.json）

复用现有链路：tools/bgm/remote.py（rssh / scp）、tools/bgm/remote/bgm_worker.py（选卡让道、打分、归一化）、
tools/bgm/deliver.py loudnorm（−16 LUFS / −1 dBTP / 48 kHz，config/bgm.json output）、tools/bgm/agent.py gate（同一套闸门阈值）。
不改生产代码；只用 gpu33:3（借道 client 前缀 stylev2-bgm）。现实编配 = ACE-Step cover 任务，以幻想编配为 src_audio（同 seed / 同调 / 同速）。
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "bgm"))
import remote as RM  # noqa: E402
import deliver as D  # noqa: E402
from agent import gate, score_gen  # noqa: E402

OUT = ROOT / "data" / "music" / "v2_style"
PAGE = ROOT / "data" / "review_pages" / "v2_style" / "music.html"
LOCAL_WORKER = Path(__file__).resolve().parent / "bgm_theme_worker.py"
GPU = 3
DUR_GEN = 48.0
TAIL = " Instrumental only, no vocals."
NEG = "vocals, singing, voice, choir, humming, rap, lyrics, spoken word, crowd noise, distortion, harsh noise"
LYRICS = "[Intro]\n[Instrumental]\n[Verse]\n[Instrumental]\n[Chorus]\n[Instrumental]\n[Outro]\n[Instrumental]"

THEMES = [
    {"key": "A", "name": "外滩夜光 · Nu-Disco / French House", "bpm": 118, "keyscale": "F minor", "cover_strength": 0.5,
     "why": "四拍舞曲律动最像时装大片/品牌片的通用语言，弦乐 + 合成器和弦 = 艳丽、贵；Rhodes 带一点海派爵士色。整季最稳的底色。",
     "fantasy": {
         "caption": "Glossy nu-disco and French house for a Shanghai fashion editorial at night. Four-on-the-floor kick, crisp "
                    "offbeat open hi-hats, octave-jumping disco bass, filtered funk guitar chops, lush string swells and "
                    "synth chord stabs carrying one memorable four-bar hook, a touch of jazzy Rhodes. Bright, sleek, "
                    "luxurious, confident, champagne city lights. Polished modern mix, wide stereo, punchy low end.",
         "instruments": "四拍底鼓、反拍开镲、八度跳 disco 贝斯、滤波放克吉他、弦乐铺垫、合成器和弦 stab、Rhodes",
         "clap": "glossy nu-disco french house with strings and synth stabs, four on the floor",
         "inst_tags": ["disco bass", "strings", "synth stabs", "funk guitar", "four on the floor drums"],
         "curve": [[0, 0.45], [8, 0.7], [16, 0.9], [40, 0.9], [48, 0.5]]},
     "reality": {
         "caption": "Lo-fi late-night city piano version of the same hook. Soft felt piano carrying the melody, muted Rhodes "
                    "chords, sparse brushed drums and a soft kick, round warm bass, faint tape hiss. Intimate, cool, lonely "
                    "but elegant, restrained dynamics, clean modern mix.",
         "instruments": "柔音钢琴（主旋律）、闷 Rhodes、稀疏刷鼓 + 轻底鼓、圆暖贝斯、轻微磁带底噪",
         "clap": "lo-fi late night piano with brushed drums and soft bass",
         "inst_tags": ["felt piano", "rhodes", "brushed drums", "soft bass"],
         "curve": [[0, 0.35], [12, 0.5], [36, 0.55], [48, 0.3]]}},
    {"key": "B", "name": "静安秀场 · Runway Deep House", "bpm": 122, "keyscale": "A minor", "cover_strength": 0.55,
     "why": "秀场 T 台的标准声音：克制、冷艳、循环感强，对白下面不抢；动机短，适合每集反复出现成为‘声音 logo’。",
     "fantasy": {
         "caption": "Sleek runway deep house for a high-fashion catwalk show in Shanghai. Steady four-on-the-floor kick, deep "
                    "rolling sub bass, crisp hi-hats and claps, a hypnotic plucked synth motif over airy pads, a short "
                    "staccato string ostinato rising in the second half, glossy filter sweeps. Cool, chic, glamorous, "
                    "magnetic, high-end boutique energy. Clean, expensive-sounding modern mix.",
         "instruments": "四拍底鼓、滚动 sub 贝斯、清脆踩镲 + 拍手、拨弦合成器动机、空气感 pad、断奏弦乐 ostinato、滤波扫频",
         "clap": "sleek runway deep house with plucked synth motif, sub bass and staccato strings",
         "inst_tags": ["sub bass", "plucked synth", "synth pad", "staccato strings", "house drums"],
         "curve": [[0, 0.45], [8, 0.65], [20, 0.85], [40, 0.9], [48, 0.5]]},
     "reality": {
         "caption": "Stripped-down minimal version of the same motif. The motif played on a muted upright piano, soft analog "
                    "pad, slow sparse kick and a quiet shaker, subtle sub bass, lots of space. Cold, reflective, tired "
                    "after-hours mood, close and intimate, warm lo-fi texture, still polished.",
         "instruments": "闷音立式钢琴（动机）、柔和模拟 pad、稀疏底鼓 + 轻沙锤、轻 sub 贝斯、大量留白",
         "clap": "minimal muted piano with soft pad and sparse kick, reflective late night",
         "inst_tags": ["upright piano", "synth pad", "sparse kick", "shaker"],
         "curve": [[0, 0.3], [12, 0.45], [36, 0.5], [48, 0.3]]}},
    {"key": "C", "name": "海派霓虹 · Shanghai City Pop × Jazz", "bpm": 104, "keyscale": "Eb major", "cover_strength": 0.6,
     "why": "上海辨识度最高：30 年代海派爵士（闷音小号、七/九和弦）+ 80 年代 city pop 的霓虹感；艳丽、俏皮，但律动不是四拍，铺满整季时比 A/B 更‘有性格’也更挑场景。",
     "fantasy": {
         "caption": "Shanghai city pop with jazz-age glamour for a fashion magazine spread. Groovy sixteenth-note hi-hats and "
                    "tight backbeat, slap bass, sparkling Rhodes with lush seventh and ninth chords, bright brass section "
                    "stabs, a muted trumpet answering phrase, sweeping strings, a touch of glossy synth. Vivid, colorful, "
                    "flirtatious, nostalgic yet modern, neon night drive by the river. Warm polished mix.",
         "instruments": "十六分踩镲 + 紧凑反拍、slap 贝斯、Rhodes（七/九和弦）、铜管组 stab、闷音小号应答句、弦乐、少量合成器",
         "clap": "city pop with jazz chords, slap bass, rhodes, brass stabs and muted trumpet",
         "inst_tags": ["slap bass", "rhodes", "brass section", "muted trumpet", "strings"],
         "curve": [[0, 0.45], [8, 0.7], [18, 0.85], [40, 0.9], [48, 0.5]]},
     "reality": {
         "caption": "Smoky lo-fi jazz version of the same melody. Solo jazz piano with seventh chords carrying the tune, soft "
                    "brushed snare and ride cymbal, walking upright bass, a distant muted trumpet phrase, gentle tape "
                    "saturation. Quiet, melancholic, rainy apartment at three in the morning, intimate and restrained, "
                    "still refined.",
         "instruments": "爵士钢琴独奏（主旋律）、刷鼓 + ride 镲、行走低音提琴、远处闷音小号、轻磁带饱和",
         "clap": "smoky lo-fi jazz piano trio with brushed drums, upright bass and muted trumpet",
         "inst_tags": ["jazz piano", "upright bass", "brushed drums", "muted trumpet"],
         "curve": [[0, 0.3], [12, 0.45], [36, 0.5], [48, 0.3]]}},
]


def jsave(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def log(*a):
    line = f"{time.strftime('%H:%M:%S')} " + " ".join(str(x) for x in a)
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "run.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def seed_of(key: str) -> int:
    return int(hashlib.sha256(f"stylev2-theme-{key}".encode()).hexdigest()[:7], 16)


def build():
    cands, briefs = [], {}
    for t in THEMES:
        s = seed_of(t["key"])
        for arr in ("fantasy", "reality"):
            a = t[arr]
            cid = f"{t['key']}_{arr}"
            c = {"id": cid, "caption": a["caption"] + TAIL, "lyrics": LYRICS, "bpm": t["bpm"], "keyscale": t["keyscale"],
                 "timesignature": 4, "duration": DUR_GEN, "seed": s, "negative": NEG}
            if arr == "reality":
                c.update(cover_of=f"{t['key']}_fantasy", cover_strength=t["cover_strength"])
            cands.append(c)
            briefs[cid] = {"duration_s": DUR_GEN - 2, "bpm": {"min": t["bpm"] - 4, "max": t["bpm"] + 4, "target": t["bpm"]},
                           "energy_curve": a["curve"], "instrumentation": a["inst_tags"], "clap_text": a["clap"],
                           "loopable": False}
    return cands, briefs


def gen_cfg():
    cfg = json.loads((ROOT / "config" / "bgm.json").read_text(encoding="utf-8"))
    gen = copy.deepcopy(cfg["generation"])
    gen["allowed_gpus"] = [GPU]   # 只用借到的 gpu33:3
    # XL int8 实测峰值 8–9 GB（bgm.json _tiers_doc）；gpu33:3 已借给本任务，ComfyUI 不会接别人的活 → 余量从 3 GB+ 降到 ~4 GB，
    # 让 XL（50 步）能在 14 GB 空闲上跑；不够仍按原顺序退 turbo → CPU
    for t in gen["tiers"]:
        if t["model"] == "acestep-v15-xl-sft" and t.get("quant"):
            t["need_mb"] = 13000
    return cfg, gen


def wait_job(host_gen: dict, jid: str, what: str, max_h: float = 3.0) -> dict:
    jd = f"{host_gen['workdir']}/jobs/{jid}"
    last, t_end = None, time.time() + max_h * 3600
    while time.time() < t_end:
        res = RM.read_json(host_gen["host"], f"{jd}/result.json")
        if res:
            return res
        pr = RM.read_json(host_gen["host"], f"{jd}/progress.json") or {}
        st = (pr.get("state"), pr.get("cand"), pr.get("model"))
        if st != last:
            log(f"{what} {jid}: {json.dumps({k: v for k, v in pr.items() if k != 't'}, ensure_ascii=False)[:300]}")
            last = st
        if not RM.alive(host_gen, jid) and not RM.read_json(host_gen["host"], f"{jd}/result.json"):
            raise RM.RemoteError(RM.ssh(host_gen["host"], f"tail -c 1500 {jd}/worker.log 2>/dev/null || true"))
        time.sleep(20)
    raise RM.RemoteError(f"{jid} 超时")


def submit_gen(gen: dict, cfg: dict, cands: list[dict], jid: str, seed_files: dict | None = None) -> dict:
    """投生成作业（只用 GPU 道 GPU）并等完；seed_files = {候选 id: 远端已有 raw.wav 路径}（retake 时把幻想编配拷进新作业目录当 cover 源）"""
    wd = gen["workdir"]
    jd = f"{wd}/jobs/{jid}"
    work = OUT / "work"
    work.mkdir(parents=True, exist_ok=True)
    RM.ssh(gen["host"], f"mkdir -p {jd}")
    for cid, src in (seed_files or {}).items():
        RM.ssh(gen["host"], f"cp {src} {jd}/{cid}.raw.wav")
    RM.put(gen["host"], RM.WORKER, f"{wd}/bgm_worker.py")
    RM.put(gen["host"], LOCAL_WORKER, f"{wd}/v2style_bgm_worker.py")
    lj = work / f"job_{jid}.json"
    jsave(lj, {"id": jid, "gen": gen, "out": cfg["output"], "candidates": cands, "score": False})
    RM.put(gen["host"], lj, f"{jd}/job.json")
    pid = RM.ssh(gen["host"], f"cd {wd} || exit 1; nohup {gen['python']} v2style_bgm_worker.py run --job {jd}/job.json "
                              f"> {jd}/worker.log 2>&1 < /dev/null & echo $! > {jd}/worker.pid; cat {jd}/worker.pid").strip()
    log(f"生成作业 {jid} 已投 {gen['host']} pid={pid}（只允许 GPU{GPU}）")
    res = wait_job(gen, jid, "生成")
    if not res.get("ok"):
        raise RuntimeError(f"生成失败：{res.get('error')}\n{res.get('trace', '')[-1500:]}")
    g = res["gen"]
    log(f"生成完成：device={g.get('device')} gpu={g.get('gpu')} tier={g.get('tier')} lm={g.get('lm')} "
        f"vram_peak={g.get('vram_peak_mb')} 候选={json.dumps(g.get('cands'), ensure_ascii=False)} yielded={g.get('yielded')}")
    return g


def deliver(src: Path, dst: Path, cfg: dict) -> dict:
    """两遍 loudnorm（deliver.loudnorm）；ffmpeg 动态模式够不到目标（瞬态尖、峰值因子大：A_reality 首轮实测只到 −19.98 LUFS）
    → 192 kHz 过采样快速限幅把差值补上，再走一遍 loudnorm。两次结果都记录。"""
    tgt, tp = cfg["output"]["lufs"], cfg["output"]["true_peak_db"]
    r = D.loudnorm(src, dst, tgt, tp)
    if abs(r["output_i"] - tgt) <= 0.5:
        return r
    gain = round(tgt - r["input_i"] + 0.3, 1)
    lim = src.with_name(src.stem + ".lim.flac")
    D.subprocess.run([D.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af",
                      f"aresample=192000,volume={gain}dB,alimiter=limit=0.80:attack=0.1:release=10:level=0:latency=1,aresample=48000",
                      "-c:a", "flac", "-sample_fmt", "s32", str(lim)], check=True, capture_output=True, timeout=300)
    r2 = D.loudnorm(lim, dst, tgt, tp)
    r2.update(first_try=r, pre=f"192 kHz 过采样快速限幅（+{gain} dB，limit 0.80 / attack 0.1 ms / release 10 ms）后再两遍 loudnorm")
    return r2


def score_and_deliver(gen: dict, cfg: dict, cands: list[dict], briefs: dict, jid: str, g: dict) -> list[dict]:
    """打分：bgm.json score_host（gpu36 CPU），每条一个作业（每条 clap_text / BPM 不同）→ 交付响度 → 闸门"""
    jd = f"{gen['workdir']}/jobs/{jid}"
    work = OUT / "work"
    made = [c for c in cands if (g["cands"].get(c["id"]) or {}).get("raw")]
    sgen = score_gen(gen) or gen
    sjobs = {}
    for c in made:
        sid = f"{jid}_{c['id']}"
        RM.ssh(sgen["host"], f"mkdir -p {sgen['workdir']}/jobs/{sid}")
        RM._scp(["-3", f"{gen['host']}:{jd}/{c['id']}.raw.wav", f"{sgen['host']}:{sgen['workdir']}/jobs/{sid}/{c['id']}.raw.wav"],
                f"→ {sgen['host']} {c['id']}", 900)
        sj = {"id": sid, "gen": dict(sgen, cpu_threads=12), "out": cfg["output"], "tempo_tol": cfg["soft"]["tempo_tol"],
              "brief": briefs[c["id"]], "candidates": [c], "score": True}
        RM.submit(sgen, sj, work, cmd="score")
        sjobs[c["id"]] = sid
        log(f"打分作业 {sid} 已投 {sgen['host']}")
    metrics = {}
    for cid, sid in sjobs.items():
        sres = wait_job(sgen, sid, "打分")
        metrics[cid] = (sres.get("metrics") or {}).get(cid) or {"error": sres.get("error") or "无度量"}
    rows = []
    for c in cands:
        m = metrics.get(c["id"]) or {"error": (g["cands"].get(c["id"]) or {}).get("error") or "未生成"}
        if "error" not in m:
            src = work / f"{c['id']}.src.flac"
            RM.get(sgen["host"], f"{sgen['workdir']}/jobs/{sjobs[c['id']]}/{c['id']}.flac", src)
            m["delivery"] = deliver(src, OUT / f"{c['id']}.flac", cfg)
        ok, fails, flags = gate(m, briefs[c["id"]], cfg)
        tier = g.get("tier") or {}
        rows.append({**{k: c.get(k) for k in ("id", "seed", "bpm", "keyscale", "caption", "negative", "cover_of", "cover_strength")},
                     "task": (g["cands"].get(c["id"]) or {}).get("task"), "gen_s": (g["cands"].get(c["id"]) or {}).get("gen_s"),
                     "model": tier.get("model"), "steps": tier.get("steps"), "quant": tier.get("quant"),
                     "lm": g.get("lm") and not c.get("cover_of"), "device": g.get("device"), "gpu": g.get("gpu"), "job": jid,
                     "score_job": sjobs.get(c["id"]), "metrics": m, "gate_pass": ok, "gate_fail": fails, "flags": flags,
                     "file": f"data/music/v2_style/{c['id']}.flac" if "error" not in m else None})
        log(f"{c['id']} pass={ok} fail={fails} flags={flags} " + json.dumps({k: m.get(k) for k in (
            "vocal_rel_db", "p_vocal", "clip_ratio", "longest_gap_s", "clap", "tempo_bpm", "duration_s")}, ensure_ascii=False))
    return rows


def motif_sim(rows: list[dict]) -> float | None:
    """幻想 vs 现实编配的旋律 / 和声相似度：逐帧 chroma 余弦均值（score_host CPU，tools/v2style/bgm_chroma_sim.py）；
    对照 = 不同主题之间（幻想 X vs 现实 Y）的均值。写进每条现实编配的 metrics.motif_sim"""
    _, gen = gen_cfg()
    sgen = score_gen(gen) or gen
    jobs = f"{sgen['workdir']}/jobs"
    RM.put(sgen["host"], Path(__file__).resolve().parent / "bgm_chroma_sim.py", f"{jobs}/stylev2_chroma_sim.py")
    files = {r["id"]: f"{jobs}/{r['score_job']}/{r['id']}.raw.wav" for r in rows if r.get("score_job")}
    lj = OUT / "work" / "chroma_files.json"
    jsave(lj, files)
    RM.put(sgen["host"], lj, f"{jobs}/stylev2_chroma_files.json")
    out = RM.ssh(sgen["host"], f"cd {jobs} && OMP_NUM_THREADS=8 nice {sgen['python']} stylev2_chroma_sim.py stylev2_chroma_files.json",
                 timeout=900)
    sims = json.loads(out.strip().splitlines()[-1])
    for r in rows:
        if r["id"] in sims["pair"]:
            r["metrics"]["motif_sim"] = sims["pair"][r["id"]]
    log(f"动机相似度 {json.dumps(sims, ensure_ascii=False)}")
    return sims.get("cross_theme_mean")


def run():
    cfg, gen = gen_cfg()
    cands, briefs = build()
    jid = f"stylev2-bgm_{int(time.time())}"
    g = submit_gen(gen, cfg, cands, jid)
    rows = score_and_deliver(gen, cfg, cands, briefs, jid, g)
    cross = motif_sim(rows)
    jsave(OUT / "themes.json", {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "job": jid, "gen": g, "gates": cfg["gates"],
                                "output": cfg["output"], "themes": THEMES, "motif_cross_theme_mean": cross, "candidates": rows})
    page()


def retake(spec: list[tuple[str, float]]):
    """现实编配重出：同一条幻想编配做 cover 源、同 seed，只换 cover 强度。新条目追加（原条保留）"""
    cfg, gen = gen_cfg()
    st = json.loads((OUT / "themes.json").read_text(encoding="utf-8"))
    cands0, briefs0 = build()
    by = {c["id"]: c for c in cands0}
    cands, briefs, seeds = [], {}, {}
    for k, s in spec:
        cid = f"{k}_reality_s{int(round(s * 100))}"
        cands.append(dict(by[f"{k}_reality"], id=cid, cover_strength=s))
        briefs[cid] = briefs0[f"{k}_reality"]
        seeds[f"{k}_fantasy"] = f"{gen['workdir']}/jobs/{st['job']}/{k}_fantasy.raw.wav"
    jid = f"stylev2-bgm_{int(time.time())}_retake"
    g = submit_gen(gen, cfg, cands, jid, seed_files=seeds)
    rows = score_and_deliver(gen, cfg, cands, briefs, jid, g)
    allrows = [r for r in st["candidates"]] + rows
    st["motif_cross_theme_mean"] = motif_sim(allrows)
    st["candidates"] = allrows
    st.setdefault("retakes", []).append({"job": jid, "gen": g, "spec": spec, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    jsave(OUT / "themes.json", st)
    page()


def resim():
    """只重算动机相似度（已有打分作业目录里的 raw.wav）"""
    st = json.loads((OUT / "themes.json").read_text(encoding="utf-8"))
    st["motif_cross_theme_mean"] = motif_sim(st["candidates"])
    jsave(OUT / "themes.json", st)
    page()


# ------------------------------------------------------------------ 试听页
STYLE_NOTE = """<p><b>整季一条主题，两种编配。</b>同一个 4 小节动机贯穿全季：幻想段 = 亮、满、四拍律动（合成器 + 弦乐 + 舞曲鼓）；
现实段 = 同调、同速、同旋律走向，换成钢琴 / Rhodes 领奏、稀疏鼓、lo-fi 质感。现实编配不是另写一首，而是 ACE-Step <i>cover</i>
任务以幻想编配为源音频重编配（同 seed），所以两条的旋律骨架和结构对得上，剪辑时可以在幻想↔现实之间直接交叉淡入。</p>
<ul>
<li><b>速度</b>：104–122 BPM（都市步行/T 台步速；现实编配同速，用半拍感的稀疏鼓显得慢）。</li>
<li><b>调式</b>：小调为主（F 小调 / A 小调：冷艳、有欲望感）；C 案用降 E 大调 + 七/九和弦（海派爵士的俏皮与怀旧）。</li>
<li><b>乐器</b>：幻想 = 四拍底鼓、disco/sub 贝斯、弦乐、合成器和弦、Rhodes、（C 案）铜管与闷音小号；现实 = 钢琴领奏、Rhodes、刷鼓、低音、pad、少量磁带质感。</li>
<li><b>制作质感</b>：现代、干净、宽立体声、低频有力但不轰；现实编配也保持“杂志级”干净度，lo-fi 只做温度不做脏。</li>
<li><b>情绪曲线</b>：幻想 = 起 0.45 → 8 s 进律动 → 16–20 s 满 → 尾部收；现实 = 0.3 起、始终不超过 0.55，留白给对白。</li>
<li><b>为什么是这三种</b>：nu-disco / French house 与秀场 deep house 是时装大片、品牌片最常用的“贵”的律动；上海味靠海派爵士和声与闷音小号点到为止，不用民乐符号。三案按“上海辨识度”递增：A 最通用、B 最克制、C 最有海派性格。</li>
<li><b>纯器乐</b>：caption 明写 no vocals，负向词排除人声；闸门 vocal_rel_db ≤ −20 dB（或 ≤ −24 时 p_vocal ≤ 0.5）。</li>
</ul>"""


def page():
    d = json.loads((OUT / "themes.json").read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in d["candidates"]}
    gates = d["gates"]
    e = html.escape
    parts = [f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>V2 整季主题配乐候选</title>
<style>body{{font-family:system-ui,"Microsoft YaHei",sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#222;line-height:1.55}}
h1{{font-size:22px}}h2{{font-size:18px;margin-top:32px;border-bottom:1px solid #ddd;padding-bottom:4px}}
.pair{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:16px}}.card{{border:1px solid #ddd;border-radius:8px;padding:12px;background:#fafafa}}
.card h3{{margin:0 0 6px;font-size:15px}}audio{{width:100%;margin:6px 0}}table{{border-collapse:collapse;font-size:13px;width:100%}}
td{{padding:2px 6px;border-bottom:1px solid #eee;vertical-align:top}}td:first-child{{color:#666;white-space:nowrap;width:110px}}
.cap{{font-size:12px;color:#555}}.fail{{color:#b00}}.ok{{color:#070}}.note{{font-size:14px}}</style></head><body>
<h1>V2 整季主题配乐候选（3 主题 × 幻想 / 现实）</h1>
<p class="note">生成 {e(d['generated_at'])}，作业 {e(d['job'])}；响度已统一到 {d['output']['lufs']} LUFS / {d['output']['true_peak_db']} dBTP / 48 kHz，可直接 A/B。
集级配乐仍按 L-118（剪辑锁定后按整集配），这里只定整季主题。</p>
<div class="note">{STYLE_NOTE}</div>"""]
    for t in d["themes"]:
        parts.append(f"<h2>{e(t['key'])}. {e(t['name'])}</h2><p class='note'>{e(t['why'])}　|　{t['bpm']} BPM · {e(t['keyscale'])} · "
                     f"现实编配 = cover（源为幻想编配）</p><div class='pair'>")
        ids = [f"{t['key']}_fantasy"] + sorted(i for i in rows if i.startswith(f"{t['key']}_reality"))
        for cid in ids:
            arr = "fantasy" if cid.endswith("_fantasy") else "reality"
            r = rows.get(cid) or {}
            label = "幻想编配" if arr == "fantasy" else f"现实编配（cover 强度 {r.get('cover_strength')}）"
            m = r.get("metrics") or {}
            parts.append(f"<div class='card'><h3>{label}　<span class='{'ok' if r.get('gate_pass') else 'fail'}'>"
                         f"{'闸门通过' if r.get('gate_pass') else '闸门未过'}</span></h3>")
            if r.get("file"):
                parts.append(f"<audio controls preload='none' src='../../music/v2_style/{e(Path(r['file']).name)}'></audio>")
            dv = m.get("delivery") or {}
            model = f"ACE-Step 1.5 {r.get('model')}（{r.get('steps')} 步{'，int8' if r.get('quant') else ''}{'，LM 1.7B' if r.get('lm') else ''}）"
            task = "text2music" if arr == "fantasy" else f"cover（源 = {t['key']}_fantasy，强度 {r.get('cover_strength')}）"
            gate_s = "、".join(r.get("gate_fail") or []) or "全部通过"
            flags = "、".join(r.get("flags") or [])
            tbl = [("乐器", t[arr]["instruments"]),
                   ("时长", f"{m.get('duration_s')} s"),
                   ("BPM", f"参数 {r.get('bpm')}；实测 {m.get('tempo_bpm')}"),
                   ("人声", f"vocal_rel_db {m.get('vocal_rel_db')}（≤ {gates['vocal_rel_db_max']}）；p_vocal {m.get('p_vocal')}"),
                   ("削波", f"clip_ratio {m.get('clip_ratio')}（≤ {gates['clip_ratio_max']}）"),
                   ("空白", f"longest_gap {m.get('longest_gap_s')} s（≤ {gates['longest_gap_s_max']}）"),
                   ("CLAP", f"{m.get('clap')}（≥ {gates['clap_min']}）；energy_r {m.get('energy_r')}"),
                   *([("动机相似", f"与幻想编配 chroma 相似度 {m['motif_sim']}（不同主题之间对照均值 {d.get('motif_cross_theme_mean')}；"
                                 "越高 = 旋律/和声越像同一首）")] if m.get("motif_sim") is not None else []),
                   ("响度", f"{dv.get('output_i')} LUFS / {dv.get('output_tp')} dBTP（{dv.get('normalization_type')}）"
                           + (f"；首轮 loudnorm 只到 {dv['first_try']['output_i']} LUFS → {dv.get('pre')}" if dv.get("first_try") else "")),
                   ("闸门", gate_s + (f"；提示：{flags}" if flags else "")),
                   ("生成", f"{model}；{task}；seed {r.get('seed')}；{r.get('device')} GPU{r.get('gpu')}；{r.get('gen_s')} s"),
                   ("caption", f"<span class='cap'>{e(r.get('caption') or '')}</span>")]
            if m.get("error"):
                tbl.insert(0, ("错误", f"<span class='fail'>{e(str(m['error']))}</span>"))
            parts.append("<table>" + "".join(f"<tr><td>{k}</td><td>{v if k in ('caption', '错误') else e(str(v))}</td></tr>"
                                             for k, v in tbl) + "</table></div>")
        parts.append("</div>")
    parts.append("</body></html>")
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text("\n".join(parts), encoding="utf-8")
    tmp.replace(PAGE)
    log(f"试听页 {PAGE}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        run()
    elif cmd == "retake":   # retake B:0.75 C:0.75
        retake([(x.split(":")[0], float(x.split(":")[1])) for x in sys.argv[2:]])
    elif cmd == "resim":
        resim()
    else:
        page()
