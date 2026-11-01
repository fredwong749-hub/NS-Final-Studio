"""VIDEO-RCA：按 V7 新口径（VQAGATE 11-02：只评台词段，回听时间戳优先；幅度 p90−p10 ≥0.004 前提 + 相关 ≥0.30 或张嘴占比 ≥0.30）
重判已出的口型实验片。服务器本机跑：绑 4 核 + nice 15（调用方负责 taskset），一条一条顺序跑。

    python v7_rejudge.py <exp_dir> [<exp_dir> ...]    → 每条一行 JSON（stdout），同时写 <exp_dir>/v7_rejudge.jsonl
镜头信息：exp_dir/jobs.json 里每臂的 v67_meta（旧镜号信息）；没有 v67_meta 的臂用 r1 时期的旧镜号表 OLD_META（只认 ep01-S4/S5/S6）。
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path("/root/work/fredw/video10_srv")
PY = "/root/work/fredw/venv_idm/bin/python"
sys.path.insert(0, str(REPO / "tools/series10_video"))
import score_clip as S  # noqa: E402

L = "data/assets/identity_refs/lin_wan/lin_wan_face_ref2va.png"
G = "data/assets/identity_refs/gu_chen/gu_chen_face_ref2va.png"
OLD_META = {
    "ep01-S4": {"people": 2, "dialogue": [{"speaker": "顾沉", "text": "第一天就加班。", "off": False}], "voiceover": None,
                "refs": {"顾沉": G, "林晚": L}, "visible": ["顾沉", "林晚"]},
    "ep01-S5": {"people": 1, "dialogue": [{"speaker": "林晚", "text": "想尽快跟上。", "off": False}], "voiceover": None,
                "refs": {"林晚": L}, "visible": ["林晚"]},
    "ep01-S6": {"people": 2, "dialogue": [{"speaker": "顾沉", "text": "别洗。", "off": False}], "voiceover": None,
                "refs": {"顾沉": G, "林晚": L}, "visible": ["顾沉", "林晚"]},
}


def one(d: Path, j: dict) -> dict | None:
    meta = j.get("v67_meta") or OLD_META.get(j["shot"])
    mp4 = (d / f"{j['shot']}__rca_{j['id']}.mp4").resolve()
    if not meta or not mp4.exists() or not [x for x in meta.get("dialogue") or [] if not x.get("off")]:
        return None
    w = S.asr_windows(mp4)
    src = "asr" if w else "stamps"
    w = w or S.dialogue_windows((j.get("score_meta") or {}).get("prompt") or j.get("prompt") or "")
    m = {**meta, "dialogue_windows": w, "window_source": src}
    r = subprocess.run([PY, str(REPO / "tools/series10_video/v7_lipsync.py"), str(mp4), json.dumps(m, ensure_ascii=False)],
                       capture_output=True, text=True, cwd=str(REPO), timeout=1800)
    ln = [x for x in r.stdout.splitlines() if x.startswith("{")]
    v7 = json.loads(ln[-1]).get("v7", {}) if ln else {"status": "未测", "why": r.stderr[-200:]}
    keep = ("status", "why", "pass_by", "corr", "corr_full", "win_amp", "win_open_frac", "win_p90", "window_source", "windows", "speaker")
    return {"exp": d.name, "arm": j["id"], "shot": j["shot"], **{k: v7.get(k) for k in keep}}


def main(dirs):
    for ds in dirs:
        d = Path(ds)
        jp = d / "jobs.json"
        if not jp.exists():
            continue
        out = []
        for j in json.loads(jp.read_text()):
            if j.get("kind") == "image":
                continue
            rec = one(d, j)
            if rec:
                print(json.dumps(rec, ensure_ascii=False), flush=True)
                out.append(rec)
        (d / "v7_rejudge.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out))


if __name__ == "__main__":
    main(sys.argv[1:])
