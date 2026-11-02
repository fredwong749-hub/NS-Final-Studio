"""STYLE-V2 音色候选（项目方 11-02 L-127：“……音色也是上海风格时尚风格。”）。

与 V1 完全切割（docs/master/V2_PLAN.md §〇）：不读 data/assets/voices 下任何 V1 ref，不改 config/voices.json。
方法与 VOICE10 相同（同一远端脚本 tools/voice10/remote_design.py / remote_clone.py，本文件不改它们）：
  Qwen3-TTS 1.7B VoiceDesign 按文字描述设计 → ref.wav（gpu36 CPU；gpu33 没装 qwen_tts / 没有该权重）
  Fun-CosyVoice3 0.5B zero-shot 以 ref.wav 复刻念两句中性试听句 → sample.wav（gpu33 卡 1，STYLE-V2 借的道；不行退 gpu36 CPU）
自动检查口径 = tools/voice10/voice10.py check（SenseVoice 回听 CER、f0、HNR 窗校正、时长、削波、ref 合理性）。
全部为文字描述设计的合成声，不克隆任何真人。

    python tools/v2style/voice_v2.py plan            写 data/assets/voices_v2/<role>/<cand>/meta.json
    python tools/v2style/voice_v2.py push            上传请求和远端脚本（gpu36 + gpu33）
    python tools/v2style/voice_v2.py design          gpu36 CPU 后台跑设计（nohup，轮询日志）
    python tools/v2style/voice_v2.py clone [--host gpu33|gpu36]
    python tools/v2style/voice_v2.py check           自动检查写回 meta.json
    python tools/v2style/voice_v2.py page            试听页 data/review_pages/v2_style/voice.html（只放过检的）+ config/voices_v2.json 草稿
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "assets" / "voices_v2"
PAGE = ROOT / "data" / "review_pages" / "v2_style" / "voice.html"
sys.path.insert(0, str(ROOT / "tools" / "netfix"))
sys.path.insert(0, str(ROOT / "tools" / "voice10"))
sys.path.insert(0, str(ROOT / "services" / "post"))
import posixpath  # noqa: E402

import rssh  # noqa: E402
import voice10 as V10  # noqa: E402  远端路径单一来源 = tools/voice10/voice10.py 的常量（不在本文件写死）

REMOTE = posixpath.join(posixpath.dirname(V10.REMOTE), "voice_v2")
VENV = V10.VENV
VD_MODEL = V10.VD_MODEL
COSY_MODEL = V10.COSY_MODEL
HF_HOME = VD_MODEL.split("/hub/", 1)[0]
CLONE_SEED = 20261102

# 每个角色读同一组中性试听句（不涉剧情）
LINES = ["今天的外滩风有点大，你把围巾带上。", "这杯咖啡我请，下次你请我吃饭。"]
# 设计 ref 念的文本（只决定音色，不进试听）：普通话版 / 沪语点缀版
REF_STD = "早上好，今天的拍摄改到下午三点，地点在武康路那家咖啡馆门口，记得早一点到，衣服我已经帮你挑好了。"
REF_WU = "侬好呀，今朝天气老灵额，下午三点我们在武康路碰头，侬不要迟到哦，衣服我已经帮侬挑好了。"

ROLES = {
    "lead_f": {
        "label": "女主 · lead_f", "gender": "female",
        "persona": "00 后上海时尚模特（23 岁）：镜头前冷感利落、私下柔软——声音要“高级、干净、有距离感”，不甜腻。",
        "cands": [
            ("a", "普通话（标准）", REF_STD,
             "female, 23 years old, a clear and cool mid-pitched voice, poised and slightly aloof, polished urban "
             "fashion-model tone, crisp articulation, standard Mandarin, natural pace"),
            ("b", "普通话（标准）", REF_STD,
             "female, 22 years old, a soft, slightly breathy mid-high voice, gentle and dreamy yet self-assured, "
             "elegant and refined, standard Mandarin, relaxed pace"),
            ("c", "上海口音普通话 + 沪语词（ref）", REF_WU,
             "女性，23岁，明亮清甜的中高音，说带一点上海口音的普通话，吴语腔调软糯、尾音轻扬，时髦俏皮，语速自然"),
        ]},
    "m1": {
        "label": "男一 · m1（成熟商人型）", "gender": "male",
        "persona": "38 岁左右的成功商人/品牌投资人：低沉磁性、稳、不急——和年轻角色拉开年龄与阶层差。",
        "cands": [
            ("a", "普通话（标准）", REF_STD,
             "male, 38 years old, a deep, low, magnetic baritone voice, calm and assured, unhurried, wealthy and "
             "sophisticated, standard Mandarin, slow measured pace"),
            ("b", "普通话（标准）", REF_STD,
             "male, 35 years old, a low, warm, resonant voice with a slight husky texture, restrained authority, "
             "smooth and confident, standard Mandarin, measured pace"),
            ("c", "上海口音普通话 + 沪语词（ref）", REF_WU,
             "男性，40岁，低沉稳重有磁性的嗓音，说带上海口音的普通话，老上海绅士腔调，讲究、从容，语速偏慢"),
        ]},
    "m2": {
        "label": "男二 · m2（同龄摄影师 / 潮牌主理人型）", "gender": "male",
        "persona": "24 岁左右的摄影师/潮牌主理人：清亮松弛、带点痞和随性——年轻、街头、轻快，和 m1 的“稳”对比最大。",
        "cands": [
            ("a", "普通话（标准）", REF_STD,
             "male, 24 years old, a clear, bright tenor voice, relaxed and casual, laid-back and a little playful, "
             "trendy young creative, standard Mandarin, natural pace"),
            ("b", "普通话（标准）", REF_STD,
             "male, 25 years old, a light, slightly raspy and airy voice, cool and chill, lazy easygoing drawl, "
             "street-style, standard Mandarin, relaxed pace"),
            ("c", "上海口音普通话 + 沪语词（ref）", REF_WU,
             "男性，24岁，清亮有活力的嗓音，说带上海口音的普通话，机灵、嘴快、有点贫，本地潮男腔调，语速偏快"),
        ]},
    "m3": {
        "label": "男三 · m3（温柔斯文白领型）", "gender": "male",
        "persona": "28 岁左右的陆家嘴白领：温柔斯文、礼貌、干净——中音、柔和，介于 m1 的低沉和 m2 的清亮之间。",
        "cands": [
            ("a", "普通话（标准）", REF_STD,
             "male, 28 years old, a gentle, soft mid-pitched voice, warm and polite, clean clear diction, "
             "considerate and calm, standard Mandarin, calm pace"),
            ("b", "普通话（标准）", REF_STD,
             "male, 29 years old, a soft, clean, slightly breathy tenor voice, mild and tender, quiet and refined, "
             "standard Mandarin, unhurried pace"),
            ("c", "上海口音普通话 + 沪语词（ref）", REF_WU,
             "男性，28岁，温和柔软的中音，说带一点上海口音的普通话，吴语腔调轻柔，斯文有礼，语速平缓"),
        ]},
}


def _j(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _w(p: Path, d) -> None:
    """原子写：先写 .tmp 再 os.replace，中途断了不会留下半截 JSON"""
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def cands():
    for role in ROLES:
        for cd in sorted((OUT / role).glob("*")):
            if (cd / "meta.json").exists():
                yield cd, _j(cd / "meta.json")


def plan() -> None:
    for ri, (role, r) in enumerate(ROLES.items()):
        for ci, (cid, accent, ref_text, instruct) in enumerate(r["cands"]):
            cd = OUT / role / cid
            if (cd / "meta.json").exists():
                continue
            cd.mkdir(parents=True, exist_ok=True)
            _w(cd / "meta.json", {
                "schema": "nsfs.voice_candidate/1", "series": "v2_draft", "role": role, "cand": cid,
                "status": "planned", "made_by": "STYLE-V2 音色助手 2026-11-02（tools/v2style/voice_v2.py）",
                "owner_quote": "……音色也是上海风格时尚风格。（项目方 11-02，L-127）",
                "persona": r["persona"], "accent": accent, "gender": r["gender"],
                "design": {"engine": "Qwen3-TTS 1.7B VoiceDesign（Apache-2.0）",
                           "weights": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign@5ecdb67327fd37bb2e042aab12ff7391903235d3",
                           "instruct": instruct, "language": "Chinese", "seed": 2026110200 + 10 * ri + ci,
                           "note": "文字描述设计的合成声，不克隆任何真人；不参考任何 V1 音色"},
                "ref_wav": "ref.wav", "ref_text": ref_text,
                "clone": {"engine": "cosyvoice3_zs", "weights":
                          "FunAudioLLM/Fun-CosyVoice3-0.5B-2512@29e01c4e8d000f4bcd70751be16fa94bf3d85a18",
                          "seed": CLONE_SEED},
                "sample_wav": "sample.wav", "sample_lines": LINES, "sample_text": "".join(LINES),
            })
            print("planned", cd.relative_to(ROOT))


def sh(host: str, cmd: str, input: bytes | None = None, timeout=600, text=True):
    p = rssh.run_retry(host, cmd, input=input, timeout=timeout, tries=3, text=text)
    if p.returncode:
        raise RuntimeError(f"{host} rc={p.returncode} {cmd[:80]}\n{(p.stderr if text else p.stderr.decode('utf-8','replace'))[-1500:]}")
    return p.stdout


def rp(cd: Path, f: str) -> str:
    return f"{REMOTE}/out/{cd.parent.name}/{cd.name}/{f}"


def put(host: str, path: str, data: bytes) -> None:
    sh(host, f"mkdir -p $(dirname {path}) && cat > {path}", input=data)


def push() -> None:
    todo = list(cands())
    design = {"model_dir": VD_MODEL, "device": "cpu",
              "items": [{"instruct": m["design"]["instruct"], "text": m["ref_text"], "seed": m["design"]["seed"],
                         "out": rp(cd, "ref.wav")} for cd, m in todo]}
    clone = {"model_dir": COSY_MODEL, "seed": CLONE_SEED,
             "items": [{"ref_wav": rp(cd, "ref.wav"), "ref_text": m["ref_text"], "lines": m["sample_lines"],
                        "out": rp(cd, "sample.wav")} for cd, m in todo]}
    v10 = ROOT / "tools" / "voice10"
    for host in ("gpu36", "gpu33"):
        sh(host, f"mkdir -p {REMOTE}/out && " + " && ".join(f"mkdir -p {REMOTE}/out/{cd.parent.name}/{cd.name}" for cd, _ in todo))
        for f in ("remote_design.py", "remote_clone.py"):
            put(host, f"{REMOTE}/{f}", (v10 / f).read_bytes())
        put(host, f"{REMOTE}/design.json", json.dumps(design, ensure_ascii=False).encode("utf-8"))
        put(host, f"{REMOTE}/clone.json", json.dumps(clone, ensure_ascii=False).encode("utf-8"))
    print("pushed", len(todo))


def launch(host: str, step: str, env: str) -> None:
    sh(host, f"cd {REMOTE} && {env} nohup {VENV}/bin/python remote_{step}.py {step}.json > {step}.log 2> {step}.err < /dev/null &")
    print("launched", host, step)


def pull(host: str, f: str) -> None:
    for cd, m in cands():
        data = rssh.run_retry(host, f"test -f {rp(cd, f)} && cat {rp(cd, f)}", timeout=300, tries=3).stdout
        if data:
            (cd / f).write_bytes(data)
            print("pulled", cd.relative_to(ROOT), f, len(data))


def check() -> None:
    import voice10 as V
    sys.path.insert(0, str(ROOT / "data" / "review_pages" / "narrator_pick" / "_tools"))
    from common import asr, metrics
    from ns_post.tts import char_error_rate
    L = V.LIMITS
    todo = [(cd, m) for cd, m in cands() if (cd / "sample.wav").exists()]
    heard = asr([cd / "sample.wav" for cd, _ in todo])
    heard_ref = asr([cd / "ref.wav" for cd, _ in todo])
    for (cd, m), h, hr in zip(todo, heard, heard_ref):
        g = m["gender"]
        s, r = metrics(cd / "sample.wav"), metrics(cd / "ref.wav")
        hn = V.hnr_corrected(cd / "sample.wav")
        peak, frac = V.clip_stats(cd / "sample.wav")
        rpeak, rfrac = V.clip_stats(cd / "ref.wav")
        cer = round(char_error_rate(m["sample_text"], h), 3)
        lo, hi = L["f0"][g]
        items = {
            "cer": {"value": cer, "asr": h, "limit": f"≤ {L['cer_max']}", "pass": cer <= L["cer_max"]},
            "f0_hz": {"value": s["f0"], "limit": f"{lo}–{hi}（{g}）", "pass": lo <= s["f0"] <= hi},
            "hnr_db": {"value": hn, "raw_uncorrected": s["hnr"], "method": "hnr_corrected（Boersma 窗校正，60 ms / 60 Hz）",
                       "limit": f"≥ {L['hnr_min']}", "pass": hn >= L["hnr_min"]},
            "duration_s": {"value": s["dur"], "limit": f"> {L['dur_min']}", "pass": s["dur"] > L["dur_min"]},
            "clipping": {"value": {"peak": round(peak, 4), "frac": round(frac, 6)},
                         "limit": f"削波样点占比 ≤ {L['clip_frac_max']}", "pass": frac <= L["clip_frac_max"]},
            "ref_ok": {"value": {"dur": r["dur"], "f0": r["f0"], "peak": round(rpeak, 4), "clip_frac": round(rfrac, 6)},
                       "limit": f"ref 时长 {L['ref_dur'][0]}–{L['ref_dur'][1]} s 且不削波",
                       "pass": L["ref_dur"][0] <= r["dur"] <= L["ref_dur"][1] and rfrac <= L["clip_frac_max"]},
        }
        m["checks"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": "tools/v2style/voice_v2.py check（口径 = tools/voice10/voice10.py check，LIMITS 同一份）",
                       "items": items, "pass": all(v["pass"] for v in items.values()),
                       "f0_sd_st": s["f0_sd"], "ref_f0_hz": r["f0"],
                       "ref_asr": {"text": hr, "cer": round(char_error_rate(m["ref_text"], hr), 3), "note": "仅参考，不计入通过"}}
        m["status"] = "passed" if m["checks"]["pass"] else "failed"
        m["ref_sha256"] = hashlib.sha256((cd / "ref.wav").read_bytes()).hexdigest()
        _w(cd / "meta.json", m)
        bad = [k for k, v in items.items() if not v["pass"]]
        print(f"{m['role']}/{m['cand']}", "PASS" if not bad else f"FAIL {bad}",
              f"cer={cer} f0={s['f0']} hnr={hn} dur={s['dur']} peak={peak:.3f} ref={r['dur']}s/{r['f0']}Hz asr={h} | ref_asr={hr}")


def page() -> None:
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    secs, reg, failed = [], {}, []
    for role, r in ROLES.items():
        rows = []
        for cd, m in cands():
            if m["role"] != role:
                continue
            c = m.get("checks") or {}
            if not c.get("pass"):
                failed.append(f"{role}/{m['cand']}")
                continue
            it = c["items"]
            media = PAGE.parent / "voice"          # 试听样音复制一份到审片页目录（原件留在 voices_v2，不删）
            media.mkdir(parents=True, exist_ok=True)
            for f in ("sample", "ref"):
                shutil.copy2(cd / f"{f}.wav", media / f"{role}_{m['cand']}_{f}.wav")
            reg.setdefault(role,{"persona": r["persona"], "candidates": []})["candidates"].append({
                "cand": m["cand"], "dir": str(cd.relative_to(ROOT)).replace(os.sep, "/"), "accent": m["accent"],
                "instruct": m["design"]["instruct"], "seed": m["design"]["seed"], "ref_sha256": m["ref_sha256"],
                "f0_hz": it["f0_hz"]["value"], "cer": it["cer"]["value"], "duration_s": it["duration_s"]["value"]})
            rows.append(
                f"<div class=c><h3>{role} · 候选 {m['cand']}</h3>"
                f"<p><b>口音：</b>{html.escape(m['accent'])}</p>"
                f"<p><b>设计描述：</b>{html.escape(m['design']['instruct'])}（seed {m['design']['seed']}）</p>"
                f"<p>试听（两句）：<br><audio controls preload=none src=\"voice/{role}_{m['cand']}_sample.wav\"></audio></p>"
                f"<p>设计原声（ref）：<small>{html.escape(m['ref_text'])}</small><br>"
                f"<audio controls preload=none src=\"voice/{role}_{m['cand']}_ref.wav\"></audio></p>"
                f"<p class=n>f0 {it['f0_hz']['value']} Hz · CER {it['cer']['value']} · 时长 {it['duration_s']['value']} s · "
                f"HNR {it['hnr_db']['value']} dB · 峰值 {it['clipping']['value']['peak']}</p></div>")
        secs.append(f"<section><h2>{html.escape(r['label'])}</h2><p class=p>{html.escape(r['persona'])}</p>"
                    + ("".join(rows) or "<p>（本角色暂无过检候选）</p>") + "</section>")
    PAGE.write_text(f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>V2 音色候选 · 上海时尚</title>
<style>body{{font:15px/1.6 system-ui,sans-serif;margin:20px auto;max-width:1100px;color:#111;background:#fafafa}}
section{{margin:28px 0}}.c{{display:inline-block;vertical-align:top;width:330px;margin:8px;padding:12px;background:#fff;border:1px solid #ddd;border-radius:8px}}
h3{{margin:0 0 6px}}p{{margin:6px 0}}audio{{width:300px}}small{{color:#666}}.n{{color:#333;font-size:13px}}.p{{color:#555}}</style>
<h1>V2 音色候选（上海风格 · 时尚感）</h1>
<p>每个候选读同一组中性句：“{LINES[0]}”“{LINES[1]}”。全部为文字描述设计的合成声，不克隆任何真人；与 V1 音色无关。
本页只列通过自动检查的候选（回听 CER ≤ 0.2、音高在性别范围、HNR ≥ 3 dB、无削波）。待项目方挑选，未启用。</p>
{''.join(secs)}""", encoding="utf-8")
    _w(ROOT / "config" / "voices_v2.json", {
        "_comment": "V2 音色候选草稿——待项目方挑选，未启用。与 config/voices.json（V1）无关；角色名待 V2 剧本定稿后替换。",
        "status": "draft_pending_owner_pick", "enabled": False, "made_by": "STYLE-V2 音色助手 2026-11-02",
        "owner_quote": "……音色也是上海风格时尚风格。（项目方 11-02，L-127）",
        "engine": "cosyvoice3_zs（Qwen3-TTS VoiceDesign 设计 ref → Fun-CosyVoice3 zero-shot）",
        "review_page": str(PAGE.relative_to(ROOT)).replace(os.sep, "/"), "roles": reg, "failed_not_listed": failed})
    print("page", PAGE, "failed:", failed)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "push", "design", "clone", "pull", "check", "page", "status"])
    ap.add_argument("--host", default="gpu33")
    ap.add_argument("--file", default="sample.wav")
    a = ap.parse_args()
    if a.cmd == "plan":
        plan()
    elif a.cmd == "push":
        push()
    elif a.cmd == "design":
        launch("gpu36", "design", f"export HF_HOME={HF_HOME} HF_HUB_OFFLINE=1 OMP_NUM_THREADS=16 CUDA_VISIBLE_DEVICES='';")
    elif a.cmd == "clone":
        dev = "1" if a.host == "gpu33" else "''"
        launch(a.host, "clone", f"export HF_HOME={HF_HOME} HF_HUB_OFFLINE=1 OMP_NUM_THREADS=16 "
                                f"CUDA_VISIBLE_DEVICES={dev} PYTHONPATH={VENV}/cosy_overlay;")
    elif a.cmd == "pull":
        pull(a.host, a.file)
    elif a.cmd == "status":
        print(sh(a.host, f"cd {REMOTE} && tail -5 *.log; tail -3 *.err; ls out/*/*"))
    elif a.cmd == "check":
        check()
    else:
        page()
